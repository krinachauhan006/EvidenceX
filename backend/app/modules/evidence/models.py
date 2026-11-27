"""Evidence ORM model.

An Evidence row is an uploaded file that belongs to exactly one case. It carries
only metadata and a pointer to the content-addressed blob on disk; the file bytes
themselves live in local storage, never in the database.

Owned by a case via a foreign key with ON DELETE CASCADE, so deleting a case
removes its evidence rows (and nothing from unrelated cases).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.db_types import GUID, TimestampMixin


class Evidence(TimestampMixin, Base):
    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )

    # Original filename is metadata ONLY. It is never used to build a storage path.
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)

    # evidence_type: "document" | "image" | "audio" (resolved server-side).
    evidence_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # Resolved/validated content type (server-mapped, not client-supplied).
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Lowercase sha256 hex digest of the content; also the storage key.
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Relative path under the storage root. Never exposed in API responses.
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)

    # Processing (Stage 3). Records start as "pending". These fields describe the
    # LATEST processing attempt; the per-run history lives in `extractions`.
    processing_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_error_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processing_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processing_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    __table_args__ = (
        Index("ix_evidence_case_uploaded", "case_id", "created_at"),
        Index("ix_evidence_sha256", "sha256"),
    )
