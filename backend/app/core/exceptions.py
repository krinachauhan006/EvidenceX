"""Domain exception hierarchy and FastAPI handlers.

Business code raises these domain errors; mapping to HTTP happens in one place so
routers and services stay free of transport concerns.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.core.logging import get_logger
from app.core.schema import SCHEMA_OUTDATED_MESSAGE, is_missing_schema_error

logger = get_logger(__name__)


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


# Only these keys of a validation error are returned. FastAPI's default response also
# echoes ``input`` (the submitted value, or the WHOLE body when a field is missing),
# which would send passwords back in error responses.
_SAFE_ERROR_KEYS = ("type", "loc", "msg")


async def _validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    detail = [{k: err[k] for k in _SAFE_ERROR_KEYS if k in err} for err in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(detail)})


async def _database_error_handler(
    _: Request, exc: OperationalError | ProgrammingError
) -> JSONResponse:
    """A table or column the code needs is missing: the database has not been migrated
    to this version. Answer 503 with what to do, instead of an opaque 500. Any other
    database error is re-raised unchanged (it stays a 500 and is logged as before)."""
    if not is_missing_schema_error(exc):
        raise exc
    # Only the error class is logged: the SQL statement and its parameters (e-mail
    # addresses, hashes) are deliberately left out.
    logger.error(
        "database schema is older than the code (%s); run 'alembic upgrade head'",
        type(getattr(exc, "orig", exc)).__name__,
    )
    return JSONResponse(status_code=503, content={"detail": SCHEMA_OUTDATED_MESSAGE})


def register_exception_handlers(app: FastAPI) -> None:
    """Register domain exception handlers on the app."""
    app.add_exception_handler(EvidenceXError, _evidencex_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        RequestValidationError,
        _validation_error_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(OperationalError, _database_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ProgrammingError, _database_error_handler)  # type: ignore[arg-type]
