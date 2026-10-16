"""
shared/response.py

Standardised API response models for AuroLab.

All API endpoints return one of these shapes:
  SuccessResponse  — data + optional metadata
  ErrorResponse    — error code + human message + optional details
  PaginatedResponse— data list + pagination cursor

Usage:
    from shared.response import ok, err, paginated
    return ok(data={"plan_id": "abc"}, message="Plan created")
    return err("VALIDATION_ERROR", "Volume exceeds maximum", status_code=422)
"""

from __future__ import annotations

from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Response models (for OpenAPI schema generation)
# ---------------------------------------------------------------------------

class SuccessResponse(BaseModel):
    success: bool = True
    data: Any = None
    message: str = ""
    meta: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    message: str
    details: Any = None


class PaginatedResponse(BaseModel):
    success: bool = True
    data: list = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    has_more: bool = False


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def ok(
    data: Any = None,
    message: str = "",
    meta: dict | None = None,
    status_code: int = status.HTTP_200_OK,
) -> JSONResponse:
    """Return a standardised success response."""
    return JSONResponse(
        status_code=status_code,
        content={
            "success": True,
            "data":    data,
            "message": message,
            "meta":    meta or {},
        },
    )


def err(
    error_code: str,
    message: str,
    details: Any = None,
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
) -> JSONResponse:
    """Return a standardised error response."""
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error":   error_code,
            "message": message,
            "details": details,
        },
    )


def paginated(
    data: list,
    total: int,
    page: int = 1,
    page_size: int = 50,
) -> JSONResponse:
    """Return a standardised paginated list response."""
    return JSONResponse(
        status_code=200,
        content={
            "success":   True,
            "data":      data,
            "total":     total,
            "page":      page,
            "page_size": page_size,
            "has_more":  (page * page_size) < total,
        },
    )