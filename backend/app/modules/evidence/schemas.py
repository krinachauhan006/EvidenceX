"""Pydantic response schemas for evidence.

The storage path is intentionally NOT exposed; callers reference evidence by id
and download via the dedicated endpoint.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

EvidenceType = Literal["document", "image", "audio", "tabular", "email", "video"]
ProcessingStatus = Literal["pending", "processing", "completed", "failed"]


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    original_filename: str
    evidence_type: EvidenceType
    mime_type: str
    byte_size: int
    sha256: str
    processing_status: ProcessingStatus
    processing_error: str | None
    processing_error_code: str | None = None
    processing_started_at: datetime | None = None
    processing_completed_at: datetime | None = None
    processing_attempts: int = 0
    # Exposed under the product-facing name "uploaded_at" (backed by created_at).
    uploaded_at: datetime = Field(validation_alias="created_at")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def external_worker(self) -> bool:
        """True when this server leaves the file type to the external processing worker
        (EXTERNAL_WORKER_MIMES), so the UI can say "waiting" instead of "failed"."""
        from app.core.config import get_settings

        return self.mime_type in get_settings().external_worker_mimes

    @computed_field  # type: ignore[prop-decorator]
    @property
    def browser_processing(self) -> bool:
        """True when an editor's browser may process this item instead of the worker."""
        from app.core.config import get_settings
        from app.modules.processing.browser_service import browser_processable

        return browser_processable(self.mime_type, get_settings())


class EvidenceList(BaseModel):
    items: list[EvidenceOut]
    total: int
