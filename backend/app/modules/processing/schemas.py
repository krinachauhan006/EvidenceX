"""Pydantic schemas for the processing API. Storage paths are never exposed."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.evidence.schemas import EvidenceType, ProcessingStatus
from app.modules.processing.locators import Locator

RunStatus = Literal["completed", "failed"]
Outcome = Literal["ok", "partial", "needs_ocr", "empty"]
SkipReason = Literal["already_completed", "already_processing", "no_extractor"]
# "reviewed" once a person has stored a correction (see segment_reviews).
ReviewStatus = Literal["unreviewed", "reviewed"]


class WarningOut(BaseModel):
    code: str
    message: str
    detail: dict[str, Any] | None = None


class ExtractionOut(BaseModel):
    """One extraction run (history entry)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    evidence_id: uuid.UUID
    case_id: uuid.UUID
    run_number: int
    run_status: RunStatus
    is_current: bool
    extractor: str
    extractor_version: str
    source_sha256: str
    outcome: Outcome | None
    error_code: str | None
    error_message: str | None
    doc_metadata: dict[str, Any]
    warnings: list[WarningOut]
    segment_count: int
    duration_ms: int
    started_at: datetime
    recorded_at: datetime = Field(validation_alias="created_at")


class ExtractionList(BaseModel):
    items: list[ExtractionOut]
    total: int


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    extraction_id: uuid.UUID
    seq: int
    segment_type: str
    text: str | None
    data: dict[str, Any] | None
    locator: Locator
    page: int | None
    t_start: float | None
    t_end: float | None
    engine_confidence: float | None
    language: str | None
    # Segments hold the ORIGINAL extracted text and are never edited. A human
    # correction lives in ``segment_reviews``; the newest one is reported here.
    review_status: ReviewStatus = "unreviewed"
    reviewed_text: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None


class SegmentList(BaseModel):
    items: list[SegmentOut]
    total: int
    limit: int
    offset: int


class ProcessRequest(BaseModel):
    force: bool = False
    # Speech model for this run (audio only). Must be available locally; it is never
    # downloaded and never replaced by a different model. None = configured default.
    audio_model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._-]{1,64}$")


class AudioModelOut(BaseModel):
    name: str
    repo: str
    available: bool
    size_bytes: int | None
    problem: str | None
    is_default: bool


class AudioModelList(BaseModel):
    default: str
    default_available: bool
    items: list[AudioModelOut]


class SkippedItem(BaseModel):
    evidence_id: uuid.UUID
    reason: SkipReason


class ProcessAccepted(BaseModel):
    queued: list[uuid.UUID]
    skipped: list[SkippedItem]


class ProcessingStatusOut(BaseModel):
    evidence_id: uuid.UUID
    status: ProcessingStatus
    error: str | None
    error_code: str | None
    attempts: int
    started_at: datetime | None
    completed_at: datetime | None
    # True when an earlier successful run is still available, even if the latest
    # attempt failed.
    has_current_extraction: bool
    current_extraction: ExtractionOut | None


class ProcessingItemOut(BaseModel):
    evidence_id: uuid.UUID
    original_filename: str
    evidence_type: EvidenceType
    status: ProcessingStatus
    error_code: str | None
    attempts: int
    outcome: Outcome | None
    segment_count: int
    run_number: int | None
    extractor_available: bool


class StatusCounts(BaseModel):
    total: int = 0
    pending: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0


class CaseProcessingSummary(BaseModel):
    counts: StatusCounts
    items: list[ProcessingItemOut]
