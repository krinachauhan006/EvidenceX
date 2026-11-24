"""add processing columns to evidence

Additive only: nullable columns and one integer with a server default, so every
existing evidence row stays valid (status unchanged, attempts start at 0).

Revision ID: 0003_evidence_processing_cols
Revises: 0002_create_evidence
Create Date: 2026-11-14
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic. (version_num is VARCHAR(32): keep ids short.)
revision: str = "0003_evidence_processing_cols"
down_revision: str | None = "0002_create_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("evidence") as batch:
        batch.add_column(sa.Column("processing_error_code", sa.String(length=48), nullable=True))
        batch.add_column(
            sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column("processing_completed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "processing_attempts", sa.Integer(), nullable=False, server_default="0"
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("evidence") as batch:
        batch.drop_column("processing_attempts")
        batch.drop_column("processing_completed_at")
        batch.drop_column("processing_started_at")
        batch.drop_column("processing_error_code")
