"""
shared/exceptions.py

Domain exceptions for AuroLab services.

Hierarchy:
    AurolabError
    ├── ProtocolError
    │   ├── GenerationError
    │   ├── ValidationError
    │   └── SafetyBlockError
    ├── SimulationError
    │   ├── CollisionError
    │   └── SimTimeoutError
    ├── RAGError
    │   ├── EmbeddingError
    │   └── IngestionError
    ├── VisionError
    └── FleetError
        ├── SchedulingError
        └── ResourceConflictError
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class AurolabError(Exception):
    """Base exception for all AuroLab errors."""

    def __init__(self, message: str, code: str = "AUROLAB_ERROR", **context) -> None:
        super().__init__(message)
        self.code    = code
        self.context = context

    def to_dict(self) -> dict:
        return {
            "error":   self.code,
            "message": str(self),
            **self.context,
        }


# ---------------------------------------------------------------------------
# Protocol errors
# ---------------------------------------------------------------------------

class ProtocolError(AurolabError):
    """Raised when protocol generation or parsing fails."""


class GenerationError(ProtocolError):
    """LLM failed to generate a valid protocol."""

    def __init__(self, message: str, instruction: str = "", **ctx) -> None:
        super().__init__(message, code="GENERATION_ERROR", instruction=instruction, **ctx)


class ProtocolValidationError(ProtocolError):
    """Protocol failed safety or structural validation."""

    def __init__(self, message: str, errors: list[str] | None = None, **ctx) -> None:
        super().__init__(message, code="VALIDATION_ERROR", errors=errors or [], **ctx)


class SafetyBlockError(ProtocolError):
    """Instruction was blocked by the safety gate."""

    def __init__(self, instruction: str, reason: str = "") -> None:
        super().__init__(
            f"Safety block: instruction rejected — {reason or 'hazardous content detected'}",
            code="SAFETY_BLOCK",
            instruction=instruction[:100],
            reason=reason,
        )


# ---------------------------------------------------------------------------
# Simulation errors
# ---------------------------------------------------------------------------

class SimulationError(AurolabError):
    """Raised when digital twin simulation encounters an unrecoverable error."""


class CollisionError(SimulationError):
    """Robot arm collision detected during simulation."""

    def __init__(self, command_index: int, description: str = "") -> None:
        super().__init__(
            f"Collision at command {command_index}: {description}",
            code="COLLISION",
            command_index=command_index,
            description=description,
        )


class SimTimeoutError(SimulationError):
    """Simulation did not complete within the timeout window."""

    def __init__(self, timeout_s: float) -> None:
        super().__init__(
            f"Simulation timed out after {timeout_s}s",
            code="SIM_TIMEOUT",
            timeout_s=timeout_s,
        )


# ---------------------------------------------------------------------------
# RAG errors
# ---------------------------------------------------------------------------

class RAGError(AurolabError):
    """Raised when the retrieval-augmented generation pipeline fails."""


class EmbeddingError(RAGError):
    """Embedding model failed to encode a query or document."""

    def __init__(self, message: str, text_preview: str = "") -> None:
        super().__init__(message, code="EMBEDDING_ERROR", text_preview=text_preview[:80])


class IngestionError(RAGError):
    """Document ingestion into ChromaDB failed."""

    def __init__(self, source: str, reason: str = "") -> None:
        super().__init__(
            f"Ingestion failed for {source}: {reason}",
            code="INGESTION_ERROR",
            source=source,
        )


# ---------------------------------------------------------------------------
# Vision errors
# ---------------------------------------------------------------------------

class VisionError(AurolabError):
    """Raised when the vision layer cannot detect or parse lab state."""

    def __init__(self, message: str, backend: str = "", **ctx) -> None:
        super().__init__(message, code="VISION_ERROR", backend=backend, **ctx)


# ---------------------------------------------------------------------------
# Fleet errors
# ---------------------------------------------------------------------------

class FleetError(AurolabError):
    """Raised by the orchestration / fleet management layer."""


class SchedulingError(FleetError):
    """Could not produce a valid schedule for the given plans and robots."""

    def __init__(self, message: str, plan_count: int = 0, robot_count: int = 0) -> None:
        super().__init__(
            message, code="SCHEDULING_ERROR",
            plan_count=plan_count, robot_count=robot_count,
        )


class ResourceConflictError(FleetError):
    """A required resource could not be acquired."""

    def __init__(self, resource_id: str, held_by: str = "") -> None:
        super().__init__(
            f"Resource {resource_id} held by {held_by}",
            code="RESOURCE_CONFLICT",
            resource_id=resource_id,
            held_by=held_by,
        )