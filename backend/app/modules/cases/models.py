"""Case ORM model.

A Case is the top-level container that owns all evidence and derived data. Owned
tables added in later stages MUST declare a foreign key to ``cases.id`` with
``ondelete="CASCADE"`` so that deleting a case removes all of its data and nothing
from unrelated cases.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Index, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.db_types import GUID, TimestampMixin


class Case(TimestampMixin, Base):
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Status values: "open" | "archived". Archiving preserves all case data.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    # Explicit per-case consent before any evidence text is sent to an external AI
    # provider. Off by default; only an owner can change it (audited).
    ai_processing_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    __table_args__ = (Index("ix_cases_status_updated_at", "status", "updated_at"),)
