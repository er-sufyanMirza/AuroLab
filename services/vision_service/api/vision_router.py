"""
aurolab/services/vision_service/api/vision_router.py

POST /api/v1/vision/detect      — Submit image, receive LabState
GET  /api/v1/vision/current     — Last known LabState (no image needed)
POST /api/v1/vision/mock        — Inject a mock scenario for testing
GET  /api/v1/vision/scenarios   — List available mock scenarios
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel

from services.vision_service.core.lab_state import LabState
from services.vision_service.core.vision_engine import VisionEngine

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/vision", tags=["Vision"])


class MockScenarioRequest(BaseModel):
    scenario: str = "bca_assay"


class LabStateSummaryResponse(BaseModel):
    snapshot_id: str
    source: str
    overall_confidence: float
    occupied_slots: list[int]
    attention_slots: list[int]
    tip_rack_slots: list[int]
    warnings: list[str]
    labware_map: dict[str, str]   # slot str → labware type string


def _state_to_response(state: LabState) -> LabStateSummaryResponse:
    return LabStateSummaryResponse(
        snapshot_id=state.snapshot_id,
        source=state.source,
        overall_confidence=round(state.overall_confidence, 3),
        occupied_slots=state.occupied_slots(),
        attention_slots=state.attention_slots(),
        tip_rack_slots=state.tip_rack_slots(),
        warnings=state.warnings,
        labware_map={str(k): v for k, v in state.to_labware_map().items()},
    )


@router.post(
    "/detect",
    response_model=LabStateSummaryResponse,
    summary="Submit a lab deck image for labware detection",
)
async def detect_lab_state(
    request: Request,
    file: UploadFile = File(description="JPEG or PNG image of the robot deck"),
) -> LabStateSummaryResponse:
    engine: VisionEngine = request.app.state.vision_engine

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty image file")

    try:
        state = engine.detect(image_bytes=image_bytes)
    except Exception as exc:
        log.error("vision_detect_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Vision detection failed: {exc}",
        ) from exc

    # Store as current state
    request.app.state.current_lab_state = state
    return _state_to_response(state)


@router.get(
    "/current",
    response_model=LabStateSummaryResponse,
    summary="Get the last detected lab state",
)
async def get_current_lab_state(request: Request) -> LabStateSummaryResponse:
    state: LabState | None = getattr(request.app.state, "current_lab_state", None)
    if not state:
        # Auto-run mock detection as fallback so orchestrator always has something
        engine: VisionEngine = request.app.state.vision_engine
        state = engine.detect(mock_scenario="bca_assay")
        request.app.state.current_lab_state = state
    return _state_to_response(state)


@router.post(
    "/mock",
    response_model=LabStateSummaryResponse,
    summary="Inject a mock lab state scenario (for testing)",
)
async def inject_mock_scenario(
    body: MockScenarioRequest,
    request: Request,
) -> LabStateSummaryResponse:
    engine: VisionEngine = request.app.state.vision_engine
    available = engine.available_mock_scenarios()

    if body.scenario not in available:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scenario '{body.scenario}'. Available: {available}",
        )

    state = engine.detect(mock_scenario=body.scenario)
    request.app.state.current_lab_state = state
    log.info("mock_scenario_injected", scenario=body.scenario)
    return _state_to_response(state)


@router.get(
    "/scenarios",
    summary="List available mock scenarios",
)
async def list_scenarios(request: Request) -> dict:
    engine: VisionEngine = request.app.state.vision_engine
    return {
        "scenarios": engine.available_mock_scenarios(),
        "current_backend": engine.backend.value,
    }