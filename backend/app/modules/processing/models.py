"""Extraction run history and segments.

``extractions`` is append-only: every attempt that reaches a result is one row
(a "run"), either ``completed`` or ``failed``. At most one completed run per
evidence item is ``is_current``. Reprocessing adds a run and moves the current
marker; it never edits or deletes older runs or their segments, so anything that
later anchors to a segment id stays valid.

Both tables cascade from ``evidence`` and ``cases``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.db_types import GUID, TimestampMixin, utcnow

# JSON everywhere; JSONB on Postgres.
JsonType = JSON().with_variant(JSONB(), "postgresql")


class Extraction(TimestampMixin, Base):
    __tablename__ = "extractions"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )

    # The evidence item's attempt counter at claim time (1, 2, 3, ...).
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # "completed" | "failed"
    run_status: Mapped[str] = mapped_column(String(16), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    extractor: Mapped[str] = mapped_column(String(32), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(32), nullable=False)
    # Hash of the evidence content this run actually read.
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    # "ok" | "partial" | "needs_ocr" | "empty"; null for failed runs.
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    doc_metadata: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    warnings: Mapped[list] = mapped_column(JsonType, nullable=False, default=list)
    segment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        UniqueConstraint("evidence_id", "run_number", name="uq_extractions_evidence_run"),
        # At most one current run per evidence item.
        Index(
            "uq_extractions_current",
            "evidence_id",
            unique=True,
            sqlite_where=sql_text("is_current = 1"),
            postgresql_where=sql_text("is_current = true"),
        ),
        Index("ix_extractions_case", "case_id"),
    )


class ExtractionSegment(Base):
    __tablename__ = "extraction_segments"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    extraction_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("extractions.id", ondelete="CASCADE"), nullable=False
    )
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )

    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # starts at 0
    segment_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # Extractor output. Untrusted data: stored and shown as text, never interpreted.
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict | None] = mapped_column(JsonType, nullable=True)

    # Typed locator (source of truth) plus promoted, indexed copies of a few values.
    locator: Mapped[dict] = mapped_column(JsonType, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    t_start: Mapped[float | None] = mapped_column(Float, nullable=True)
    t_end: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Engine-reported confidence in [0, 1]. Separate from claim-level confidence.
    engine_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        UniqueConstraint("extraction_id", "seq", name="uq_segments_extraction_seq"),
        Index("ix_segments_evidence_page", "evidence_id", "page"),
        Index("ix_segments_case", "case_id"),
    )
