"""Extraction error taxonomy.

Extractors raise these. The runner stores ``code`` as the machine-readable error
code and ``message`` as the human-readable error. Messages must never contain
extracted file content or filesystem paths.
"""

from __future__ import annotations

# Codes recorded on a failed item / failed run.
CORRUPT_FILE = "corrupt_file"
PASSWORD_REQUIRED = "password_required"
UNSUPPORTED_CONTENT = "unsupported_content"
DEPENDENCY_MISSING = "dependency_missing"
MODEL_UNAVAILABLE = "model_unavailable"
LIMIT_EXCEEDED = "limit_exceeded"
TIMEOUT = "timeout"
STORAGE_MISSING = "storage_missing"
INTERNAL_ERROR = "internal_error"
# Speech-model problems other than "not downloaded" (model_unavailable).
MODEL_INVALID = "model_invalid"  # files present but damaged or not a usable model
RESOURCE_EXHAUSTED = "resource_exhausted"  # out of memory or a similar resource limit
MODEL_INIT_FAILED = "model_init_failed"  # any other failure while starting the engine

# Longest error message stored; keeps one bad file from bloating the table.
MAX_ERROR_MESSAGE_CHARS = 1000


class ExtractionError(Exception):
    """Base class for expected extraction failures."""

    code: str = INTERNAL_ERROR

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message[:MAX_ERROR_MESSAGE_CHARS]


class CorruptFileError(ExtractionError):
    code = CORRUPT_FILE


class PasswordRequiredError(ExtractionError):
    code = PASSWORD_REQUIRED


class UnsupportedContentError(ExtractionError):
    code = UNSUPPORTED_CONTENT


class DependencyMissingError(ExtractionError):
    code = DEPENDENCY_MISSING


class ModelUnavailableError(ExtractionError):
    code = MODEL_UNAVAILABLE


class LimitExceededError(ExtractionError):
    code = LIMIT_EXCEEDED


class ExtractionTimeoutError(ExtractionError):
    code = TIMEOUT


class StorageMissingError(ExtractionError):
    code = STORAGE_MISSING


class ModelInvalidError(ExtractionError):
    code = MODEL_INVALID


class ResourceExhaustedError(ExtractionError):
    code = RESOURCE_EXHAUSTED


class ModelInitError(ExtractionError):
    code = MODEL_INIT_FAILED
