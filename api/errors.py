"""
Standardized API error types and response formatting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    """Machine-readable API error codes."""

    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    VALIDATION_ERROR = "validation_error"
    RATE_LIMITED = "rate_limited"
    BAD_REQUEST = "bad_request"
    INTERNAL_ERROR = "internal_error"
    NOT_FOUND = "not_found"


@dataclass
class ApiError(Exception):
    """Structured API error with HTTP status and optional field details."""

    code: ErrorCode
    message: str
    status: int = 400
    details: list[dict[str, str]] | dict[str, Any] | None = None

    @classmethod
    def unauthorized(cls, message: str = "Authentication required") -> ApiError:
        return cls(ErrorCode.UNAUTHORIZED, message, status=401)

    @classmethod
    def forbidden(cls, message: str = "Access denied") -> ApiError:
        return cls(ErrorCode.FORBIDDEN, message, status=403)

    @classmethod
    def validation(
        cls,
        message: str,
        *,
        details: list[dict[str, str]] | None = None,
    ) -> ApiError:
        return cls(
            ErrorCode.VALIDATION_ERROR,
            message,
            status=400,
            details=details,
        )

    @classmethod
    def rate_limited(cls, *, retry_after_s: int) -> ApiError:
        return cls(
            ErrorCode.RATE_LIMITED,
            "Rate limit exceeded",
            status=429,
            details={"retry_after_s": retry_after_s},
        )

    @classmethod
    def bad_request(cls, message: str) -> ApiError:
        return cls(ErrorCode.BAD_REQUEST, message, status=400)

    @classmethod
    def internal(cls, message: str = "An internal error occurred") -> ApiError:
        return cls(ErrorCode.INTERNAL_ERROR, message, status=500)


@dataclass(frozen=True)
class ErrorBody:
    """JSON error envelope returned to clients."""

    code: str
    message: str
    request_id: str
    details: list[dict[str, str]] | dict[str, Any] | None = None


def format_error_response(error: ApiError, request_id: str) -> dict[str, Any]:
    """Build a consistent JSON error payload."""
    body = ErrorBody(
        code=error.code.value,
        message=error.message,
        request_id=request_id,
        details=error.details,
    )
    return {"error": body.__dict__}


def validation_detail(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}