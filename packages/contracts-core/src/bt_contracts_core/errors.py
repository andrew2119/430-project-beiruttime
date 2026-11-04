"""CP B-03: stable, additive errors with opaque support references."""
import re
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class AccessDenied(PermissionError):
    """Explicit policy denial; unlike an operating-system PermissionError."""


class PublicError(Exception):
    """Closed, intentionally public domain outcome; never wrap arbitrary exception text."""
    def __init__(self, code: str, message: str, *, status: int = 400, details: dict[str, Any] | None = None):
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', code) or not isinstance(status, int) or not 400 <= status <= 599 or len(message) > 500:
            raise ValueError('Invalid public error contract')
        super().__init__(code)
        self.code, self.message, self.status, self.details = code, message, status, details or {}


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: str
    message: str
    request_id: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


def error_body(code: str, message: str, request_id: str, *, details: dict[str, Any] | None = None, **extra: Any) -> dict:
    return ErrorEnvelope(error=ErrorDetail(
        code=code, message=message, request_id=request_id, details={**(details or {}), **extra},
    )).model_dump(mode='json')
