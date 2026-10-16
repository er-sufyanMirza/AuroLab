"""
aurolab/services/translation_service/api/generate_router.py

POST /api/v1/generate   — Convert NL instruction → validated robotic protocol
GET  /api/v1/protocols/{protocol_id}  — Retrieve a previously generated protocol
"""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..core.llm_engine import AurolabLLMEngine, GeneratedProtocol, SafetyLevel

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["Protocol Generation"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    instruction: str = Field(
        min_length=10,
        max_length=2000,
        description="Natural language lab instruction to convert into a robotic protocol.",
        examples=["Perform a BCA protein assay on 8 samples at 562nm absorbance"],
    )
    doc_type_filter: str | None = Field(
        default=None,
        description="Restrict RAG context to a specific document type: 'protocol', 'SOP', 'paper'.",
    )
    top_k_chunks: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Number of knowledge base chunks to inject as context.",
    )
    return_sources: bool = Field(
        default=True,
        description="Include source citations in the response.",
    )


class GenerateResponse(BaseModel):
    protocol_id: str
    title: str
    description: str
    steps: list[dict]
    reagents: list[str]
    equipment: list[str]
    safety_level: str
    safety_notes: list[str]
    sources_used: list[dict] | None = None
    confidence_score: float
    generation_ms: float
    model_used: str


def _protocol_to_response(
    protocol: GeneratedProtocol,
    return_sources: bool,
) -> GenerateResponse:
    return GenerateResponse(
        protocol_id=protocol.protocol_id,
        title=protocol.title,
        description=protocol.description,
        steps=[s.model_dump(exclude_none=False) for s in protocol.steps],
        reagents=protocol.reagents,
        equipment=protocol.equipment,
        safety_level=protocol.safety_level.value,
        safety_notes=protocol.safety_notes,
        sources_used=protocol.sources_used if return_sources else None,
        confidence_score=protocol.confidence_score,
        generation_ms=protocol.generation_ms,
        model_used=protocol.model_used,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/generate",
    response_model=GenerateResponse,
    status_code=status.HTTP_200_OK,
    summary="Convert a natural language lab instruction into a validated robotic protocol",
)
async def generate_protocol(
    body: GenerateRequest,
    request: Request,
) -> GenerateResponse:
    llm_engine: AurolabLLMEngine = request.app.state.llm_engine
    protocol_id = str(uuid.uuid4())

    log.info("generate_request",
             protocol_id=protocol_id,
             instruction_chars=len(body.instruction),
             doc_type_filter=body.doc_type_filter)

    try:
        protocol = llm_engine.generate(
            instruction=body.instruction,
            protocol_id=protocol_id,
            top_k_chunks=body.top_k_chunks,
            doc_type_filter=body.doc_type_filter,
        )
    except ValueError as exc:
        # Safety block
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        # LLM failure — log full error and return it in detail for debugging
        log.error("generate_failed", protocol_id=protocol_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Protocol generation failed: {exc}",
        ) from exc
    except Exception as exc:
        # Catch-all — surfaces unexpected errors instead of hiding them
        log.error("generate_unexpected", protocol_id=protocol_id,
                  error=type(exc).__name__, detail=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Unexpected error ({type(exc).__name__}): {exc}",
        ) from exc

    # Store in protocol registry for later retrieval
    registry = request.app.state.protocol_registry
    registry[protocol_id] = protocol

    return _protocol_to_response(protocol, body.return_sources)


@router.get(
    "/protocols/{protocol_id}",
    response_model=GenerateResponse,
    summary="Retrieve a previously generated protocol by ID",
)
async def get_protocol(protocol_id: str, request: Request) -> GenerateResponse:
    registry = request.app.state.protocol_registry
    protocol = registry.get(protocol_id)
    if not protocol:
        raise HTTPException(status_code=404, detail="Protocol not found")
    return _protocol_to_response(protocol, return_sources=True)