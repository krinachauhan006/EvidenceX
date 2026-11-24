"""create cases table

Revision ID: 0001_create_cases
Revises:
Create Date: 2026-11-07
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.core.db_types import GUID

# revision identifiers, used by Alembic.
revision: str = "0001_create_cases"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_cases_status_updated_at",
        "cases",
        ["status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_cases_status_updated_at", table_name="cases")
    op.drop_table("cases")
