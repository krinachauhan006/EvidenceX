"""Domain exception hierarchy and FastAPI handlers.

Business code raises these domain errors; mapping to HTTP happens in one place so
routers and services stay free of transport concerns.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class EvidenceXError(Exception):
    """Base class for all domain errors."""

    status_code: int = 500
    message: str = "Internal server error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message


class NotFoundError(EvidenceXError):
    """A requested resource does not exist (or is out of the caller's scope)."""

    status_code = 404
    message = "Resource not found"


class ValidationFailedError(EvidenceXError):
    """A domain-level validation rule was violated."""

    status_code = 422
    message = "Validation failed"


class ConflictError(EvidenceXError):
    """The request conflicts with the current state of the resource."""

    status_code = 409
    message = "Conflict"


class BadRequestError(EvidenceXError):
    """The request is malformed or violates an input rule (e.g. an unsupported,
    empty, or oversized upload)."""

    status_code = 400
    message = "Bad request"


async def _evidencex_error_handler(_: Request, exc: EvidenceXError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


def register_exception_handlers(app: FastAPI) -> None:
    """Register domain exception handlers on the app."""
    app.add_exception_handler(EvidenceXError, _evidencex_error_handler)  # type: ignore[arg-type]
