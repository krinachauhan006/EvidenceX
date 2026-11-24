"""Pydantic schemas for the analysis API (claims, entities, relationships, potential
contradictions, review). ORM objects are never returned directly."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ClaimReviewStatus = Literal["unreviewed", "needs_verification", "verified", "rejected"]
ContradictionStatus = Literal["unreviewed", "confirmed", "rejected", "unresolved", "resolved"]
ResolutionStatus = Literal["unresolved", "confirmed", "merged", "rejected"]
Grounding = Literal["grounded", "insufficient"]
AlternativeBasis = Literal["source_supported", "machine_hypothesis", "human"]

REVIEWER_MAX = 128
NOTE_MAX = 4000


# --- runs --------------------------------------------------------------------------


class AnalysisRunOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    status: Literal["running", "completed", "failed"]
    method: str
    started_at: datetime
    completed_at: datetime | None
    error: str | None
    stats: dict[str, Any]


class AnalysisRunState(BaseModel):
    run: AnalysisRunOut | None


# --- claims ------------------------------------------------------------------------


class MentionOut(BaseModel):
    entity_id: uuid.UUID
    entity_type: str
    display_name: str
    mention_text: str
    role: str | None = None


class ClaimBrief(BaseModel):
    id: uuid.UUID
    evidence_id: uuid.UUID
    evidence_name: str
    evidence_type: str
    segment_id: uuid.UUID | None
    modality: str
    quote: str
    claim_text: str
    locator: dict[str, Any] | None
    event_time: dict[str, Any] | None
    review_status: ClaimReviewStatus
    source_current: bool


class ClaimOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    evidence_id: uuid.UUID
    evidence_name: str
    evidence_type: str
    extraction_id: uuid.UUID
    run_number: int
    source_current: bool  # False when the evidence was reprocessed after this claim
    segment_id: uuid.UUID | None
    analysis_run_id: uuid.UUID | None
    claim_text: str
    claim_type: str
    subject: str | None
    predicate: str | None
    predicate_key: str | None
    object_value: str | None
    event_time: dict[str, Any] | None
    location: str | None
    quote: str
    quote_start: int | None
    quote_end: int | None
    locator: dict[str, Any] | None
    modality: str
    grounding: Grounding
    extraction_method: str
    is_inferred: bool
    extraction_confidence: float | None
    source_engine_confidence: float | None
    uncertainty: list[str]
    review_status: ClaimReviewStatus
    reviewed_text: str | None
    review_note: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    created_at: datetime
    entities: list[MentionOut] = []
    contradiction_count: int = 0


class ClaimList(BaseModel):
    items: list[ClaimOut]
    total: int
    limit: int
    offset: int


class SegmentRef(BaseModel):
    id: uuid.UUID
    extraction_id: uuid.UUID
    seq: int
    segment_type: str
    text: str | None
    locator: dict[str, Any]
    engine_confidence: float | None


class ReviewActionOut(BaseModel):
    id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    action: str
    from_status: str | None
    to_status: str | None
    note: str | None
    payload: dict[str, Any]
    reviewer: str | None
    created_at: datetime


class RelationshipOut(BaseModel):
    id: uuid.UUID
    relation_type: str
    rationale: str
    origin: str
    review_status: ClaimReviewStatus
    via_entity_id: uuid.UUID | None
    via_entity_name: str | None
    source_claim: ClaimBrief
    target_claim: ClaimBrief
    created_at: datetime


class RelationshipList(BaseModel):
    items: list[RelationshipOut]
    total: int


class ClaimDetail(ClaimOut):
    segment: SegmentRef | None
    relationships: list[RelationshipOut]
    contradiction_ids: list[uuid.UUID]
    history: list[ReviewActionOut]


# --- entities ----------------------------------------------------------------------


class EntityOut(BaseModel):
    id: uuid.UUID
    entity_type: str
    display_name: str
    normalized_key: str
    aliases: list[str]
    resolution_status: ResolutionStatus
    merged_into_id: uuid.UUID | None
    review_status: str
    review_note: str | None
    mention_count: int
    evidence_count: int
    created_at: datetime


class EntityList(BaseModel):
    items: list[EntityOut]
    total: int


class EntityMentionOut(BaseModel):
    claim_id: uuid.UUID
    mention_text: str
    role: str | None
    claim: ClaimBrief


class CandidateOut(BaseModel):
    """Two entity records that MAY be the same thing. Never merged automatically."""

    entity_a: EntityOut
    entity_b: EntityOut
    reason: str


class CandidateList(BaseModel):
    items: list[CandidateOut]
    total: int


class EntityDetail(EntityOut):
    mentions: list[EntityMentionOut]
    candidates: list[CandidateOut]
    merged_from: list[EntityOut]
    history: list[ReviewActionOut]


# --- contradictions ----------------------------------------------------------------


class ExplanationOut(BaseModel):
    first_states: str
    second_states: str
    why: str
    uncertain: str
    would_resolve: str


class AlternativeOut(BaseModel):
    id: uuid.UUID
    explanation: str
    supporting_evidence: str | None
    weakening_evidence: str | None
    missing_information: str | None
    verification_recommendation: str | None
    basis: AlternativeBasis
    status: str
    author: str | None
    created_at: datetime


class ContradictionOut(BaseModel):
    id: uuid.UUID
    category: str
    severity: Literal["low", "medium", "high"]
    explanation: ExplanationOut
    # Heuristic match strength of the rule. Not a probability that either source is
    # wrong, and not a statement about which source is right.
    detection_confidence: float
    uncertainty: list[str]
    origin: str
    review_status: ContradictionStatus
    reviewer_decision: str | None
    resolution_note: str | None
    linked_evidence_ids: list[uuid.UUID]
    via_entity_id: uuid.UUID | None
    via_entity_name: str | None
    claim_a: ClaimBrief
    claim_b: ClaimBrief
    claims_current: bool
    alternatives: list[AlternativeOut]
    created_at: datetime
    updated_at: datetime


class ContradictionList(BaseModel):
    items: list[ContradictionOut]
    total: int


class ContradictionDetail(ContradictionOut):
    history: list[ReviewActionOut]


# --- review requests ---------------------------------------------------------------


class _ReviewBase(BaseModel):
    note: str | None = Field(default=None, max_length=NOTE_MAX)
    reviewer: str | None = Field(default=None, max_length=REVIEWER_MAX)


class ClaimReviewRequest(_ReviewBase):
    action: Literal["verify", "reject", "needs_verification", "edit", "note"]
    reviewed_text: str | None = Field(default=None, max_length=NOTE_MAX)


class RelationshipReviewRequest(_ReviewBase):
    action: Literal["verify", "reject", "needs_verification", "note"]


class EntityReviewRequest(_ReviewBase):
    action: Literal["confirm", "reject", "merge", "unmerge", "mark_distinct", "note"]
    target_entity_id: uuid.UUID | None = None


class ContradictionReviewRequest(_ReviewBase):
    action: Literal["confirm", "reject", "unresolved", "resolve", "note", "link_evidence"]
    evidence_id: uuid.UUID | None = None


class AlternativeCreate(BaseModel):
    explanation: str = Field(min_length=1, max_length=NOTE_MAX)
    supporting_evidence: str | None = Field(default=None, max_length=NOTE_MAX)
    weakening_evidence: str | None = Field(default=None, max_length=NOTE_MAX)
    missing_information: str | None = Field(default=None, max_length=NOTE_MAX)
    verification_recommendation: str | None = Field(default=None, max_length=NOTE_MAX)
    author: str | None = Field(default=None, max_length=REVIEWER_MAX)


class ReviewHistory(BaseModel):
    items: list[ReviewActionOut]
    total: int


# --- segment (transcript) corrections ----------------------------------------------


class SegmentReviewCreate(BaseModel):
    corrected_text: str = Field(min_length=1, max_length=20_000)
    note: str | None = Field(default=None, max_length=NOTE_MAX)
    reviewer: str | None = Field(default=None, max_length=REVIEWER_MAX)


class SegmentReviewOut(BaseModel):
    id: uuid.UUID
    segment_id: uuid.UUID
    evidence_id: uuid.UUID
    corrected_text: str
    note: str | None
    reviewer: str | None
    created_at: datetime


class SegmentReviewList(BaseModel):
    original_text: str | None  # the machine text, unchanged
    items: list[SegmentReviewOut]  # newest first; the first item is the current correction
    total: int


# --- review queue, graph, dashboard ------------------------------------------------


class ReviewQueueOut(BaseModel):
    claims: list[ClaimOut]
    contradictions: list[ContradictionOut]
    candidates: list[CandidateOut]
    counts: dict[str, int]


class GraphNode(BaseModel):
    id: str
    kind: Literal["evidence", "claim", "entity", "contradiction"]
    label: str
    sublabel: str | None = None
    status: str | None = None
    ref_id: uuid.UUID
    evidence_id: uuid.UUID | None = None
    data: dict[str, Any] = {}


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    kind: str
    label: str | None = None


class GraphOut(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool
    counts: dict[str, int]


class EvidenceAnalysisSummary(BaseModel):
    evidence_id: uuid.UUID
    segments: int
    claims: int
    entities: int
    relationships: int
    contradictions: int
    awaiting_review: int
    analysed: bool


class DashboardOut(BaseModel):
    evidence: dict[str, Any]
    segments: int
    claims: dict[str, Any]
    entities: dict[str, Any]
    relationships: int
    contradictions: dict[str, Any]
    review_queue: int
    latest_run: AnalysisRunOut | None
    recent_activity: list[ReviewActionOut]
    top_entities: list[EntityOut]
    claim_method: str
