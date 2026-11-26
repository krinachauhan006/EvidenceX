"""phase 2: users, sessions, case members, events, reports, consent, audit chain

Strictly additive:
- New tables: users, auth_sessions, case_members, events, event_claims, reports.
- New columns on existing tables, added in place with ALTER TABLE ADD COLUMN (no table
  rebuild, so no existing row is copied, rewritten or cascaded):
    cases.ai_processing_allowed      BOOLEAN NOT NULL DEFAULT false
    claims.superseded_by_run_id      nullable
    contradictions.via_event_id      nullable (+ index)
    review_actions.prev_hash / hash  nullable
  These columns carry no FK constraint on purpose: SQLite can only add a foreign key
  by rebuilding the table, and rebuilding ``cases`` with foreign keys enforced would
  cascade-delete case data. The service layer validates the referenced ids.

Downgrade drops only the objects created here.

Revision ID: 0007_phase2
Revises: 0006_analysis_not_null_ts
Create Date: 2026-11-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.core.db_types import GUID
from app.modules.processing.models import JsonType

revision: str = "0007_phase2"
down_revision: str | None = "0006_analysis_not_null_ts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    ]


def _case_fk() -> sa.Column:
    return sa.Column(
        "case_id", GUID(), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", TS, nullable=True),
        *_stamps(),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "user_id", GUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("last_seen_at", TS, nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_auth_sessions_user", "auth_sessions", ["user_id"])
    op.create_table(
        "case_members",
        sa.Column("id", GUID(), primary_key=True),
        _case_fk(),
        sa.Column(
            "user_id", GUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column(
            "added_by_user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *_stamps(),
        sa.UniqueConstraint("case_id", "user_id", name="uq_case_members_case_user"),
    )
    op.create_index("ix_case_members_user", "case_members", ["user_id"])

    op.create_table(
        "events",
        sa.Column("id", GUID(), primary_key=True),
        _case_fk(),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("anchor_kind", sa.String(16), nullable=False),
        sa.Column("anchor_key", sa.String(256), nullable=False),
        sa.Column(
            "anchor_entity_id",
            GUID(),
            sa.ForeignKey("entities.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_date", sa.String(10), nullable=True),
        sa.Column("date_precision", sa.String(16), nullable=False),
        sa.Column("link_basis", sa.String(16), nullable=False),
        sa.Column("association_confidence", sa.Float(), nullable=False),
        sa.Column("factors", JsonType, nullable=False),
        sa.Column("missing_links", JsonType, nullable=False),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(128), nullable=True),
        sa.Column("reviewed_at", TS, nullable=True),
        sa.Column("signature", sa.String(64), nullable=False),
        *_stamps(),
        sa.UniqueConstraint("case_id", "signature", name="uq_events_case_signature"),
    )
    op.create_index("ix_events_case_status", "events", ["case_id", "status"])
    op.create_table(
        "event_claims",
        sa.Column("id", GUID(), primary_key=True),
        _case_fk(),
        sa.Column(
            "event_id", GUID(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "claim_id", GUID(), sa.ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("account_label", sa.Text(), nullable=False),
        sa.Column("attribution", sa.String(128), nullable=True),
        sa.Column("match_reasons", JsonType, nullable=False),
        sa.Column("added_by", sa.String(16), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.UniqueConstraint("event_id", "claim_id", name="uq_event_claims_event_claim"),
    )
    op.create_index("ix_event_claims_claim", "event_claims", ["claim_id"])
    op.create_table(
        "reports",
        sa.Column("id", GUID(), primary_key=True),
        _case_fk(),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("snapshot", JsonType, nullable=False),
        sa.Column(
            "analysis_run_id",
            GUID(),
            sa.ForeignKey("analysis_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_reports_case_kind", "reports", ["case_id", "kind", "created_at"])

    # In-place column additions (ALTER TABLE ADD COLUMN; no rebuild).
    op.add_column(
        "cases",
        sa.Column("ai_processing_allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("claims", sa.Column("superseded_by_run_id", GUID(), nullable=True))
    op.add_column("contradictions", sa.Column("via_event_id", GUID(), nullable=True))
    op.create_index("ix_contradictions_event", "contradictions", ["via_event_id"])
    op.add_column("review_actions", sa.Column("prev_hash", sa.String(64), nullable=True))
    op.add_column("review_actions", sa.Column("hash", sa.String(64), nullable=True))


def _drop_column(table: str, column: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        # SQLite >= 3.35 drops a plain column in place (no rebuild, no cascade).
        op.execute(sa.text(f'ALTER TABLE "{table}" DROP COLUMN "{column}"'))
    else:
        op.drop_column(table, column)


def downgrade() -> None:
    _drop_column("review_actions", "hash")
    _drop_column("review_actions", "prev_hash")
    op.drop_index("ix_contradictions_event", table_name="contradictions")
    _drop_column("contradictions", "via_event_id")
    _drop_column("claims", "superseded_by_run_id")
    _drop_column("cases", "ai_processing_allowed")
    op.drop_index("ix_reports_case_kind", table_name="reports")
    op.drop_table("reports")
    op.drop_index("ix_event_claims_claim", table_name="event_claims")
    op.drop_table("event_claims")
    op.drop_index("ix_events_case_status", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_case_members_user", table_name="case_members")
    op.drop_table("case_members")
    op.drop_index("ix_auth_sessions_user", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("users")
