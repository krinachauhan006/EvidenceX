"""create investigation analysis tables

Adds claims, entities, claim_entities, claim_relationships, contradictions,
alternative_explanations, review_actions, segment_reviews and analysis_runs.
Only creates tables; no existing table or row is altered.

Downgrade drops exactly these tables (and their data).

Revision ID: 0005_create_analysis
Revises: 0004_create_extractions
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.db_types import GUID

revision: str = "0005_create_analysis"
down_revision: str | None = "0004_create_extractions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)


def _case() -> sa.Column:
    return sa.Column(
        "case_id", GUID(), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("id", GUID(), primary_key=True),
        _case(),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("method", sa.String(48), nullable=False),
        sa.Column("started_at", TS, nullable=True),
        sa.Column("completed_at", TS, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("stats", JSON_TYPE, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index("ix_analysis_runs_case", "analysis_runs", ["case_id", "started_at"])

    op.create_table(
        "claims",
        sa.Column("id", GUID(), primary_key=True),
        _case(),
        sa.Column(
            "evidence_id", GUID(), sa.ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "extraction_id",
            GUID(),
            sa.ForeignKey("extractions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "segment_id",
            GUID(),
            sa.ForeignKey("extraction_segments.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "analysis_run_id",
            GUID(),
            sa.ForeignKey("analysis_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.String(32), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("predicate", sa.String(128), nullable=True),
        sa.Column("predicate_key", sa.String(48), nullable=True),
        sa.Column("object_value", sa.Text(), nullable=True),
        sa.Column("event_time", JSON_TYPE, nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("quote_start", sa.Integer(), nullable=True),
        sa.Column("quote_end", sa.Integer(), nullable=True),
        sa.Column("locator", JSON_TYPE, nullable=True),
        sa.Column("modality", sa.String(16), nullable=False),
        sa.Column("grounding", sa.String(16), nullable=False),
        sa.Column("extraction_method", sa.String(48), nullable=False),
        sa.Column("is_inferred", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("extraction_confidence", sa.Float(), nullable=True),
        sa.Column("source_engine_confidence", sa.Float(), nullable=True),
        sa.Column("uncertainty", JSON_TYPE, nullable=False),
        sa.Column("review_status", sa.String(24), nullable=False, server_default="unreviewed"),
        sa.Column("reviewed_text", sa.Text(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(128), nullable=True),
        sa.Column("reviewed_at", TS, nullable=True),
        sa.Column("dedupe_key", sa.String(64), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.UniqueConstraint("case_id", "dedupe_key", name="uq_claims_case_dedupe"),
    )
    op.create_index("ix_claims_case_status", "claims", ["case_id", "review_status"])
    op.create_index("ix_claims_evidence", "claims", ["evidence_id"])
    op.create_index("ix_claims_extraction", "claims", ["extraction_id"])

    op.create_table(
        "entities",
        sa.Column("id", GUID(), primary_key=True),
        _case(),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("normalized_key", sa.String(256), nullable=False),
        sa.Column("aliases", JSON_TYPE, nullable=False),
        sa.Column("resolution_status", sa.String(16), nullable=False, server_default="unresolved"),
        sa.Column(
            "merged_into_id",
            GUID(),
            sa.ForeignKey("entities.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("review_status", sa.String(24), nullable=False, server_default="unreviewed"),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.UniqueConstraint("case_id", "entity_type", "normalized_key", name="uq_entities_key"),
    )
    op.create_index("ix_entities_case_type", "entities", ["case_id", "entity_type"])

    op.create_table(
        "claim_entities",
        sa.Column("id", GUID(), primary_key=True),
        _case(),
        sa.Column(
            "claim_id", GUID(), sa.ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "entity_id", GUID(), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("mention_text", sa.Text(), nullable=False),
        sa.Column("role", sa.String(32), nullable=True),
        sa.Column("created_at", TS, nullable=True),
        sa.UniqueConstraint(
            "claim_id", "entity_id", "mention_text", name="uq_claim_entity_mention"
        ),
    )
    op.create_index("ix_claim_entities_entity", "claim_entities", ["entity_id"])

    op.create_table(
        "claim_relationships",
        sa.Column("id", GUID(), primary_key=True),
        _case(),
        sa.Column(
            "source_claim_id",
            GUID(),
            sa.ForeignKey("claims.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_claim_id",
            GUID(),
            sa.ForeignKey("claims.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "via_entity_id",
            GUID(),
            sa.ForeignKey("entities.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("relation_type", sa.String(48), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("review_status", sa.String(24), nullable=False, server_default="unreviewed"),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.UniqueConstraint(
            "source_claim_id", "target_claim_id", "relation_type", name="uq_claim_relationship"
        ),
    )
    op.create_index("ix_relationships_case", "claim_relationships", ["case_id"])

    op.create_table(
        "contradictions",
        sa.Column("id", GUID(), primary_key=True),
        _case(),
        sa.Column(
            "claim_a_id", GUID(), sa.ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "claim_b_id", GUID(), sa.ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "via_entity_id",
            GUID(),
            sa.ForeignKey("entities.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("explanation", JSON_TYPE, nullable=False),
        sa.Column("severity", sa.String(8), nullable=False),
        sa.Column("detection_confidence", sa.Float(), nullable=False),
        sa.Column("uncertainty", JSON_TYPE, nullable=False),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("review_status", sa.String(24), nullable=False, server_default="unreviewed"),
        sa.Column("reviewer_decision", sa.Text(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("linked_evidence_ids", JSON_TYPE, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.UniqueConstraint("claim_a_id", "claim_b_id", "category", name="uq_contradiction_pair"),
    )
    op.create_index("ix_contradictions_case_status", "contradictions", ["case_id", "review_status"])

    op.create_table(
        "alternative_explanations",
        sa.Column("id", GUID(), primary_key=True),
        _case(),
        sa.Column(
            "contradiction_id",
            GUID(),
            sa.ForeignKey("contradictions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("supporting_evidence", sa.Text(), nullable=True),
        sa.Column("weakening_evidence", sa.Text(), nullable=True),
        sa.Column("missing_information", sa.Text(), nullable=True),
        sa.Column("verification_recommendation", sa.Text(), nullable=True),
        sa.Column("basis", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="proposed"),
        sa.Column("author", sa.String(128), nullable=True),
        sa.Column("created_at", TS, nullable=True),
    )
    op.create_index(
        "ix_alternatives_contradiction", "alternative_explanations", ["contradiction_id"]
    )

    op.create_table(
        "review_actions",
        sa.Column("id", GUID(), primary_key=True),
        _case(),
        sa.Column("target_type", sa.String(24), nullable=False),
        sa.Column("target_id", GUID(), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("from_status", sa.String(24), nullable=True),
        sa.Column("to_status", sa.String(24), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("payload", JSON_TYPE, nullable=False),
        sa.Column("reviewer", sa.String(128), nullable=True),
        sa.Column("created_at", TS, nullable=True),
    )
    op.create_index("ix_review_actions_target", "review_actions", ["target_type", "target_id"])
    op.create_index("ix_review_actions_case_time", "review_actions", ["case_id", "created_at"])

    op.create_table(
        "segment_reviews",
        sa.Column("id", GUID(), primary_key=True),
        _case(),
        sa.Column(
            "evidence_id", GUID(), sa.ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "segment_id",
            GUID(),
            sa.ForeignKey("extraction_segments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("corrected_text", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reviewer", sa.String(128), nullable=True),
        sa.Column("created_at", TS, nullable=True),
    )
    op.create_index("ix_segment_reviews_segment", "segment_reviews", ["segment_id", "created_at"])


def downgrade() -> None:
    for index, table in (
        ("ix_segment_reviews_segment", "segment_reviews"),
        ("ix_review_actions_case_time", "review_actions"),
        ("ix_review_actions_target", "review_actions"),
        ("ix_alternatives_contradiction", "alternative_explanations"),
        ("ix_contradictions_case_status", "contradictions"),
        ("ix_relationships_case", "claim_relationships"),
        ("ix_claim_entities_entity", "claim_entities"),
        ("ix_entities_case_type", "entities"),
        ("ix_claims_extraction", "claims"),
        ("ix_claims_evidence", "claims"),
        ("ix_claims_case_status", "claims"),
        ("ix_analysis_runs_case", "analysis_runs"),
    ):
        op.drop_index(index, table_name=table)
    for table in (
        "segment_reviews",
        "review_actions",
        "alternative_explanations",
        "contradictions",
        "claim_relationships",
        "claim_entities",
        "entities",
        "claims",
        "analysis_runs",
    ):
        op.drop_table(table)
