"""Investigation analysis records: claims, entities, relationships, potential
contradictions, alternative explanations, human review history.

Layering of evidence, never mixed:
1. original evidence (``evidence`` + blob, immutable),
2. mechanically extracted content (``extraction_segments``, immutable),
3. machine findings in these tables (claims, entities, relationships,
   contradictions). Findings point back to (2) and (1) by id; they never copy
   over or edit the extracted text. Human decisions are separate columns plus an
   append-only ``review_actions`` audit trail.

Every table is case-scoped and cascades from ``cases``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
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
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.db_types import GUID, TimestampMixin, utcnow
from app.modules.processing.models import JsonType


def _case_fk() -> Mapped[uuid.UUID]:
    return mapped_column(GUID(), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)


class AnalysisRun(TimestampMixin, Base):
    """One case-level analysis pass (claims -> entities -> relationships -> conflicts)."""

    __tablename__ = "analysis_runs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = _case_fk()
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # running|completed|failed
    method: Mapped[str] = mapped_column(String(48), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)

    __table_args__ = (Index("ix_analysis_runs_case", "case_id", "started_at"),)


class Claim(TimestampMixin, Base):
    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = _case_fk()
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False
    )
    extraction_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("extractions.id", ondelete="CASCADE"), nullable=False
    )
    # The anchor. Nullable only for claims whose source could not be established
    # (grounding = "insufficient"); such claims are never silently given a locator.
    segment_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("extraction_segments.id", ondelete="CASCADE"), nullable=True
    )
    analysis_run_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("analysis_runs.id", ondelete="SET NULL"), nullable=True
    )

    claim_text: Mapped[str] = mapped_column(Text, nullable=False)  # machine wording
    claim_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str | None] = mapped_column(Text)
    predicate: Mapped[str | None] = mapped_column(String(128))
    predicate_key: Mapped[str | None] = mapped_column(String(48))  # normalized for matching
    object_value: Mapped[str | None] = mapped_column(Text)
    event_time: Mapped[dict | None] = mapped_column(JsonType)  # raw + precision, never coerced
    location: Mapped[str | None] = mapped_column(Text)

    # Exact supporting quotation, copied verbatim from the segment text, with offsets.
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    quote_start: Mapped[int | None] = mapped_column(Integer)
    quote_end: Mapped[int | None] = mapped_column(Integer)
    locator: Mapped[dict | None] = mapped_column(JsonType)  # segment locator + refinements
    modality: Mapped[str] = mapped_column(String(16), nullable=False)
    grounding: Mapped[str] = mapped_column(String(16), nullable=False)  # grounded|insufficient

    extraction_method: Mapped[str] = mapped_column(String(48), nullable=False)
    is_inferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Model self-assessment (LLM methods only). Never a statement of factual truth.
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    # OCR/ASR engine confidence of the source segment, copied for visibility.
    source_engine_confidence: Mapped[float | None] = mapped_column(Float)
    uncertainty: Mapped[list] = mapped_column(JsonType, nullable=False, default=list)

    review_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unreviewed")
    # Human correction of the interpretation. claim_text and quote are never edited.
    reviewed_text: Mapped[str | None] = mapped_column(Text)
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(String(128))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("case_id", "dedupe_key", name="uq_claims_case_dedupe"),
        Index("ix_claims_case_status", "case_id", "review_status"),
        Index("ix_claims_evidence", "evidence_id"),
        Index("ix_claims_extraction", "extraction_id"),
    )


class Entity(TimestampMixin, Base):
    __tablename__ = "entities"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = _case_fk()
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    # Exact-match key (e.g. "NS88421"). Only identical keys share an entity record.
    normalized_key: Mapped[str] = mapped_column(String(256), nullable=False)
    aliases: Mapped[list] = mapped_column(JsonType, nullable=False, default=list)
    # unresolved | confirmed | merged | rejected
    resolution_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unresolved")
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )
    review_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unreviewed")
    review_note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("case_id", "entity_type", "normalized_key", name="uq_entities_key"),
        Index("ix_entities_case_type", "case_id", "entity_type"),
    )


class ClaimEntity(Base):
    """A mention: the exact string in a claim that refers to an entity."""

    __tablename__ = "claim_entities"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = _case_fk()
    claim_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    mention_text: Mapped[str] = mapped_column(Text, nullable=False)  # original string
    role: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("claim_id", "entity_id", "mention_text", name="uq_claim_entity_mention"),
        Index("ix_claim_entities_entity", "entity_id"),
    )


class ClaimRelationship(TimestampMixin, Base):
    __tablename__ = "claim_relationships"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = _case_fk()
    source_claim_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    target_claim_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    via_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )
    relation_type: Mapped[str] = mapped_column(String(48), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)  # rule_based|llm|human
    review_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unreviewed")

    __table_args__ = (
        UniqueConstraint(
            "source_claim_id", "target_claim_id", "relation_type", name="uq_claim_relationship"
        ),
        Index("ix_relationships_case", "case_id"),
    )


class PotentialContradiction(TimestampMixin, Base):
    __tablename__ = "contradictions"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = _case_fk()
    claim_a_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    claim_b_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    via_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    # {first_states, second_states, why, uncertain, would_resolve}
    explanation: Mapped[dict] = mapped_column(JsonType, nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)  # low|medium|high
    detection_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    uncertainty: Mapped[list] = mapped_column(JsonType, nullable=False, default=list)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    review_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unreviewed")
    reviewer_decision: Mapped[str | None] = mapped_column(Text)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    linked_evidence_ids: Mapped[list] = mapped_column(JsonType, nullable=False, default=list)

    __table_args__ = (
        UniqueConstraint("claim_a_id", "claim_b_id", "category", name="uq_contradiction_pair"),
        Index("ix_contradictions_case_status", "case_id", "review_status"),
    )


class AlternativeExplanation(Base):
    __tablename__ = "alternative_explanations"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = _case_fk()
    contradiction_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("contradictions.id", ondelete="CASCADE"), nullable=False
    )
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_evidence: Mapped[str | None] = mapped_column(Text)
    weakening_evidence: Mapped[str | None] = mapped_column(Text)
    missing_information: Mapped[str | None] = mapped_column(Text)
    verification_recommendation: Mapped[str | None] = mapped_column(Text)
    # source_supported | machine_hypothesis | human
    basis: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="proposed")
    author: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_alternatives_contradiction", "contradiction_id"),)


class ReviewAction(Base):
    """Append-only audit trail of every human review decision."""

    __tablename__ = "review_actions"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = _case_fk()
    target_type: Mapped[str] = mapped_column(String(24), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str | None] = mapped_column(String(24))
    note: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    reviewer: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_review_actions_target", "target_type", "target_id"),
        Index("ix_review_actions_case_time", "case_id", "created_at"),
    )


class SegmentReview(Base):
    """A human correction of an extracted segment (e.g. an ASR transcript).

    Append-only; the newest row is the current reviewed text. The segment's own text,
    word timestamps and probabilities are never modified.
    """

    __tablename__ = "segment_reviews"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = _case_fk()
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False
    )
    segment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("extraction_segments.id", ondelete="CASCADE"), nullable=False
    )
    corrected_text: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_segment_reviews_segment", "segment_id", "created_at"),)
