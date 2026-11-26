"""Phase 2 API schemas: events, timeline, search, reports, AI status, Q&A."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.modules.analysis.schemas import NOTE_MAX, REVIEWER_MAX, ClaimBrief, ReviewActionOut

EventStatus = Literal["proposed", "confirmed", "rejected"]


class EventMemberOut(BaseModel):
    claim: ClaimBrief
    account_label: str
    attribution: str | None
    match_reasons: list[str]
    added_by: str
    date: str | None
    date_precision: str
    date_source: str | None


class ComparisonOut(BaseModel):
    claim_a_id: uuid.UUID
    claim_b_id: uuid.UUID
    account_a: str
    account_b: str
    classification: str
    gap_minutes: int | None
    explanation: str
    is_candidate: bool


class EventOut(BaseModel):
    id: uuid.UUID
    event_type: str
    title: str
    anchor_kind: str
    anchor_key: str
    event_date: str | None
    date_precision: str
    link_basis: str
    # Heuristic score of how strongly the rules associate these claims. Not a
    # probability that the event happened, and separate from all other confidences.
    association_confidence: float
    factors: list[dict[str, Any]]
    missing_links: list[str]
    origin: str
    status: EventStatus
    review_note: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    created_at: datetime
    members: list[EventMemberOut]
    comparisons: list[ComparisonOut]
    contradiction_ids: list[uuid.UUID]


class EventList(BaseModel):
    items: list[EventOut]
    total: int


class EventDetail(EventOut):
    history: list[ReviewActionOut]


class EventReviewRequest(BaseModel):
    action: Literal["confirm", "reject", "reopen", "note", "add_claim", "remove_claim", "split"]
    claim_id: uuid.UUID | None = None
    claim_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    note: str | None = Field(default=None, max_length=NOTE_MAX)
    reviewer: str | None = Field(default=None, max_length=REVIEWER_MAX)


class EventCreate(BaseModel):
    """A reviewer-defined grouping (regroup claims the rules did not group)."""

    title: str = Field(min_length=1, max_length=300)
    event_type: str = Field(min_length=1, max_length=48, pattern=r"^[a-z_]{1,48}$")
    claim_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=NOTE_MAX)


class TimelineEventRef(BaseModel):
    id: uuid.UUID
    title: str
    status: EventStatus


class TimelineItem(BaseModel):
    claim: ClaimBrief
    date: str | None
    date_precision: str
    date_source: str | None
    time_raw: str | None
    time_precision: str | None
    start_minute: int | None
    end_minute: int | None
    tz: str | None
    events: list[TimelineEventRef]
    contradiction_ids: list[uuid.UUID]


class TimelineGroup(BaseModel):
    date: str | None  # None = "date not stated"
    items: list[TimelineItem]


class TimelineOut(BaseModel):
    groups: list[TimelineGroup]
    total: int
    undated_note: str


class SearchHit(BaseModel):
    kind: Literal["segment", "claim", "entity", "event"]
    id: uuid.UUID
    evidence_id: uuid.UUID | None
    evidence_name: str | None
    segment_id: uuid.UUID | None
    claim_id: uuid.UUID | None
    title: str
    excerpt: str
    locator: dict[str, Any] | None
    score: float
    matched: list[str]
    why: str
    review_status: str | None = None
    modality: str | None = None


class SearchOut(BaseModel):
    query: str
    expanded_terms: list[str]
    method: str
    items: list[SearchHit]
    total: int


class ReportOut(BaseModel):
    id: uuid.UUID
    kind: str
    format: str
    title: str
    version: int
    content_sha256: str
    byte_size: int
    page_count: int
    created_by: str | None
    created_at: datetime
    summary: dict[str, Any]


class ReportList(BaseModel):
    items: list[ReportOut]
    total: int


class ReportCreate(BaseModel):
    kind: Literal["investigation", "graph"] = "investigation"
    include_ai_summary: bool = False
    # Graph report scope (same filters as the interactive graph).
    entity_type: str | None = Field(default=None, max_length=32)
    evidence_id: uuid.UUID | None = None
    focus_node: str | None = Field(default=None, max_length=80)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class AskCitation(BaseModel):
    ref: str
    kind: str
    id: uuid.UUID
    evidence_name: str | None
    locator: dict[str, Any] | None
    excerpt: str


class AskStatement(BaseModel):
    text: str
    citations: list[str]
    support: Literal["supported", "interpretation", "unknown"]


class AskOut(BaseModel):
    question: str
    method: str
    answer: list[AskStatement]
    citations: list[AskCitation]
    removed_unsupported: int
    notice: str
