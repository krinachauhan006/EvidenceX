"""create extraction history and segment tables

Revision ID: 0004_create_extractions
Revises: 0003_evidence_processing_cols
Create Date: 2026-11-14
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.db_types import GUID

# revision identifiers, used by Alembic.
revision: str = "0004_create_extractions"
down_revision: str | None = "0003_evidence_processing_cols"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "extractions",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("evidence_id", GUID(), nullable=False),
        sa.Column("case_id", GUID(), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("run_status", sa.String(length=16), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("extractor", sa.String(length=32), nullable=False),
        sa.Column("extractor_version", sa.String(length=32), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=True),
        sa.Column("error_code", sa.String(length=48), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("doc_metadata", JSON_TYPE, nullable=False),
        sa.Column("warnings", JSON_TYPE, nullable=False),
        sa.Column("segment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("evidence_id", "run_number", name="uq_extractions_evidence_run"),
    )
    op.create_index(
        "uq_extractions_current",
        "extractions",
        ["evidence_id"],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
        postgresql_where=sa.text("is_current = true"),
    )
    op.create_index("ix_extractions_case", "extractions", ["case_id"])

    op.create_table(
        "extraction_segments",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("extraction_id", GUID(), nullable=False),
        sa.Column("evidence_id", GUID(), nullable=False),
        sa.Column("case_id", GUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("segment_type", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("data", JSON_TYPE, nullable=True),
        sa.Column("locator", JSON_TYPE, nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("t_start", sa.Float(), nullable=True),
        sa.Column("t_end", sa.Float(), nullable=True),
        sa.Column("engine_confidence", sa.Float(), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["extraction_id"], ["extractions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("extraction_id", "seq", name="uq_segments_extraction_seq"),
    )
    op.create_index("ix_segments_evidence_page", "extraction_segments", ["evidence_id", "page"])
    op.create_index("ix_segments_case", "extraction_segments", ["case_id"])


def downgrade() -> None:
    op.drop_index("ix_segments_case", table_name="extraction_segments")
    op.drop_index("ix_segments_evidence_page", table_name="extraction_segments")
    op.drop_table("extraction_segments")
    op.drop_index("ix_extractions_case", table_name="extractions")
    op.drop_index("uq_extractions_current", table_name="extractions")
    op.drop_table("extractions")
