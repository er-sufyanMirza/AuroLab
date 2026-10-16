"""
shared/middleware.py

FastAPI middleware for AuroLab.

Provides:
  - RequestLoggingMiddleware  — structured log per request with timing
  - ErrorHandlingMiddleware   — converts AurolabError → JSON HTTP response
  - CorrelationIdMiddleware   — injects X-Request-ID for distributed tracing
"""

from __future__ import annotations

import time
import uuid

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .exceptions import AurolabError

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Correlation ID middleware
# ---------------------------------------------------------------------------

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Injects a unique request ID into each request for distributed tracing.
    Reads X-Request-ID header if present, otherwise generates a new UUID.
    Adds the ID to the response headers.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs every HTTP request with method, path, status code, and duration.
    Skips health check and metrics endpoints to reduce log noise.
    """

    SKIP_PATHS = {"/health", "/metrics", "/favicon.ico"}

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        t0 = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - t0) * 1000, 1)

        log.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
            client=request.client.host if request.client else "unknown",
        )
        return response


# ---------------------------------------------------------------------------
# Error handling middleware
# ---------------------------------------------------------------------------

class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """
    Converts AurolabError subclasses into structured JSON HTTP responses.
    Prevents raw Python exceptions from leaking to clients in production.
    """

    # Map error codes → HTTP status codes
    _STATUS_MAP: dict[str, int] = {
        "SAFETY_BLOCK":        400,
        "VALIDATION_ERROR":    422,
        "GENERATION_ERROR":    500,
        "COLLISION":           409,
        "SIM_TIMEOUT":         504,
        "EMBEDDING_ERROR":     500,
        "INGESTION_ERROR":     500,
        "VISION_ERROR":        503,
        "SCHEDULING_ERROR":    500,
        "RESOURCE_CONFLICT":   409,
        "AUROLAB_ERROR":       500,
    }

    async def dispatch(self, request: Request, call_next) -> Response:
        try:
            return await call_next(request)
        except AurolabError as exc:
            status = self._STATUS_MAP.get(exc.code, 500)
            log.warning(
                "aurolab_error",
                code=exc.code,
                message=str(exc),
                path=request.url.path,
                status=status,
            )
            return JSONResponse(status_code=status, content=exc.to_dict())
        except Exception as exc:
            log.error(
                "unhandled_error",
                error=type(exc).__name__,
                message=str(exc),
                path=request.url.path,
                exc_info=True,
            )
            return JSONResponse(
                status_code=500,
                content={"error": "INTERNAL_ERROR", "message": "An unexpected error occurred"},
            )


# ---------------------------------------------------------------------------
# Helper to add all middleware to a FastAPI app
# ---------------------------------------------------------------------------

def add_middleware(app: ASGIApp) -> None:
    """Add all AuroLab middleware to a FastAPI app in the correct order."""
    from fastapi import FastAPI
    if isinstance(app, FastAPI):
        app.add_middleware(ErrorHandlingMiddleware)
        app.add_middleware(RequestLoggingMiddleware)
        app.add_middleware(CorrelationIdMiddleware)