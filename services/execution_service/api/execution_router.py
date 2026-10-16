"""
aurolab/services/execution_service/api/execution_router.py

POST /api/v1/execute   — Submit a GeneratedProtocol for simulation + plan creation
GET  /api/v1/plans/{plan_id}  — Retrieve an execution plan
GET  /api/v1/plans/           — List all plans
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..core.orchestrator import execute_protocol
from ..core.isaac_sim_bridge import SimMode
from ..core.robot_commands import ExecutionPlan, ExecutionStatus

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["Execution"])


class ExecuteRequest(BaseModel):
    protocol: dict = Field(description="GeneratedProtocol JSON from /api/v1/generate")
    sim_mode: str = Field(default="mock", pattern=r"^(mock|live)$")
    auto_correct: bool = Field(default=True)


class ExecutionSummaryResponse(BaseModel):
    plan_id: str
    protocol_id: str
    protocol_title: str
    status: str
    command_count: int
    command_breakdown: dict
    estimated_mins: float
    validation_errors: int
    sim_passed: bool | None
    is_executable: bool
    collision_description: str | None = None


def _plan_to_summary(plan: ExecutionPlan) -> ExecutionSummaryResponse:
    s = plan.summary()
    return ExecutionSummaryResponse(
        **s,
        collision_description=(
            plan.simulation_result.collision_description
            if plan.simulation_result and not plan.simulation_result.passed
            else None
        ),
    )


@router.post(
    "/execute",
    response_model=ExecutionSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Simulate and validate a protocol for robotic execution",
)
async def execute(body: ExecuteRequest, request: Request) -> ExecutionSummaryResponse:
    plan_store: dict = request.app.state.execution_plan_store

    mode = SimMode.LIVE if body.sim_mode == "live" else (
        SimMode.PYBULLET if body.sim_mode == "pybullet" else SimMode.MOCK
    )

    try:
        plan = execute_protocol(
            protocol=body.protocol,
            sim_mode=mode,
            auto_correct=body.auto_correct,
        )
    except Exception as exc:
        log.error("execute_failed", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Execution pipeline failed: {exc}",
        ) from exc

    plan_store[plan.plan_id] = plan
    return _plan_to_summary(plan)


@router.post(
    "/execute/{protocol_id}",
    status_code=status.HTTP_200_OK,
    summary="Execute a previously generated protocol by ID",
)
async def execute_by_id(
    protocol_id: str,
    request: Request,
    sim_mode: str = "mock",
    auto_correct: bool = True,
) -> dict:
    """Look up a protocol from the registry and simulate it."""
    registry: dict = request.app.state.protocol_registry
    protocol = registry.get(protocol_id)
    if not protocol:
        raise HTTPException(status_code=404,
            detail=f"Protocol {protocol_id} not found. Generate it first on the Generate page.")

    mode = SimMode.LIVE if sim_mode == "live" else (
        SimMode.PYBULLET if sim_mode == "pybullet" else SimMode.MOCK
    )
    try:
        if hasattr(protocol, "model_dump"):
            proto_dict = protocol.model_dump(mode="json")
        else:
            proto_dict = dict(protocol)

        plan = execute_protocol(
            protocol=proto_dict,
            sim_mode=mode,
            auto_correct=auto_correct,
        )
    except Exception as exc:
        log.error("execute_by_id_failed", protocol_id=protocol_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Simulation failed: {exc}",
        ) from exc

    plan_store: dict = request.app.state.execution_plan_store
    plan_store[plan.plan_id] = plan

    summary = _plan_to_summary(plan)
    return {
        **summary.__dict__,
        "protocol_id": protocol_id,
        "sim_mode": sim_mode,
        "passed": plan.simulation_result.passed if plan.simulation_result else False,
        "physics_engine": getattr(plan.simulation_result, "telemetry", {}).get(
            "physics_engine", sim_mode) if plan.simulation_result else sim_mode,
    }


@router.get(
    "/plans/{plan_id}",
    summary="Retrieve an execution plan by ID",
)
async def get_plan(plan_id: str, request: Request) -> dict:
    store: dict = request.app.state.execution_plan_store
    plan = store.get(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan.model_dump(mode="json")


@router.get(
    "/plans/",
    response_model=list[ExecutionSummaryResponse],
    summary="List all execution plans",
)
async def list_plans(request: Request) -> list[ExecutionSummaryResponse]:
    store: dict = request.app.state.execution_plan_store
    return [_plan_to_summary(p) for p in store.values()]