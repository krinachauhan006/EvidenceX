"""create evidence table

Revision ID: 0002_create_evidence
Revises: 0001_create_cases
Create Date: 2026-11-07
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.core.db_types import GUID

# revision identifiers, used by Alembic.
revision: str = "0002_create_evidence"
down_revision: str | None = "0001_create_cases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evidence",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("case_id", GUID(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("evidence_type", sa.String(length=16), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column(
            "processing_status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_evidence_case_uploaded",
        "evidence",
        ["case_id", "created_at"],
    )
    op.create_index("ix_evidence_sha256", "evidence", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_evidence_sha256", table_name="evidence")
    op.drop_index("ix_evidence_case_uploaded", table_name="evidence")
    op.drop_table("evidence")
