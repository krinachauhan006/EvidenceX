"""Analysis reads, human review, review queue, knowledge graph and dashboard.

The machine proposes; people decide. Every human decision is a ``ReviewAction``
row (append-only). Review never edits machine output: claim text, quotes, segment
text and contradiction explanations stay as generated; human wording is stored in
separate fields.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import timedelta
from typing import Any

from app.core.actor import current_actor
from app.core.config import Settings, get_settings
from app.core.db_types import utcnow
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.modules.analysis.audit import record_action
from app.modules.analysis.extract import CANDIDATE_TIERS, assess_candidate
from app.modules.analysis.models import (
    AlternativeExplanation,
    AnalysisRun,
    Claim,
    ClaimRelationship,
    Entity,
    PotentialContradiction,
    ReviewAction,
    SegmentReview,
)
from app.modules.analysis.repository import AnalysisRepository, ClaimRow
from app.modules.analysis.schemas import (
    AlternativeCreate,
    AlternativeOut,
    AnalysisRunOut,
    AnalysisRunState,
    CandidateList,
    CandidateOut,
    ClaimBrief,
    ClaimDetail,
    ClaimList,
    ClaimOut,
    ClaimReviewRequest,
    ContradictionDetail,
    ContradictionList,
    ContradictionOut,
    ContradictionReviewRequest,
    DashboardOut,
    EntityDetail,
    EntityList,
    EntityMentionOut,
    EntityOut,
    EntityReviewRequest,
    EvidenceAnalysisSummary,
    ExplanationOut,
    GraphEdge,
    GraphNode,
    GraphOut,
    MentionOut,
    RelationshipList,
    RelationshipOut,
    RelationshipReviewRequest,
    ReviewActionOut,
    ReviewHistory,
    ReviewQueueOut,
    SegmentRef,
    SegmentReviewCreate,
    SegmentReviewList,
    SegmentReviewOut,
)
from app.modules.cases.repository import CaseRepository
from app.modules.evidence.models import Evidence
from app.modules.processing.models import ExtractionSegment

DEFAULT_CLAIM_LIMIT = 100
MAX_CLAIM_LIMIT = 500
DEFAULT_REVIEWER = "unspecified"

# Claims and relationships: action -> target status, and the statuses it may leave.
CLAIM_ACTIONS: dict[str, str] = {
    "verify": "verified",
    "reject": "rejected",
    "needs_verification": "needs_verification",
}
CLAIM_TRANSITIONS: dict[str, set[str]] = {
    "unreviewed": {"verified", "rejected", "needs_verification"},
    "needs_verification": {"verified", "rejected"},
    "verified": {"needs_verification"},
    "rejected": {"needs_verification"},
}
# Potential contradictions. "confirmed" means a reviewer agrees the two sources are
# inconsistent; it says nothing about which source is right or about anyone's conduct.
CONTRADICTION_ACTIONS: dict[str, str] = {
    "confirm": "confirmed",
    "reject": "rejected",
    "unresolved": "unresolved",
    "resolve": "resolved",
}
CONTRADICTION_TRANSITIONS: dict[str, set[str]] = {
    "unreviewed": {"confirmed", "rejected", "unresolved"},
    "unresolved": {"confirmed", "rejected", "resolved"},
    "confirmed": {"resolved", "unresolved"},
    "rejected": {"unresolved"},
    "resolved": {"unresolved"},
}
OPEN_CLAIM_STATES = ("unreviewed", "needs_verification")
# Claim modalities whose text comes from OCR or speech recognition (can be misread).
MACHINE_READ_MODALITIES = ("audio", "image", "video")
OPEN_CONTRADICTION_STATES = ("unreviewed", "unresolved")


def _who(declared: str | None) -> str:
    """The logged-in account's label; a self-declared name only without login."""
    actor = current_actor()
    if actor is not None:
        return actor.label[:128]
    return ((declared or "").strip() or DEFAULT_REVIEWER)[:128]


def run_out(run: AnalysisRun) -> AnalysisRunOut:
    return AnalysisRunOut(
        id=run.id,
        case_id=run.case_id,
        status=run.status,  # type: ignore[arg-type]
        method=run.method,
        started_at=run.started_at,
        completed_at=run.completed_at,
        error=run.error,
        stats=dict(run.stats or {}),
    )


def review_out(action: ReviewAction) -> ReviewActionOut:
    return ReviewActionOut(
        id=action.id,
        target_type=action.target_type,
        target_id=action.target_id,
        action=action.action,
        from_status=action.from_status,
        to_status=action.to_status,
        note=action.note,
        payload=dict(action.payload or {}),
        reviewer=action.reviewer,
        created_at=action.created_at,
    )


def brief(claim: Claim, evidence: Evidence, source_current: bool) -> ClaimBrief:
    return ClaimBrief(
        id=claim.id,
        evidence_id=claim.evidence_id,
        evidence_name=evidence.original_filename,
        evidence_type=evidence.evidence_type,
        segment_id=claim.segment_id,
        modality=claim.modality,
        quote=claim.quote,
        claim_text=claim.claim_text,
        locator=claim.locator,
        event_time=claim.event_time,
        review_status=claim.review_status,  # type: ignore[arg-type]
        source_current=source_current,
    )


class AnalysisService:
    def __init__(self, db: Any, settings: Settings | None = None) -> None:
        self._db = db
        self._repo = AnalysisRepository(db)
        self._cases = CaseRepository(db)
        self._settings = settings or get_settings()

    # --- helpers ----------------------------------------------------------------

    def _require_case(self, case_id: uuid.UUID) -> None:
        if self._cases.get(case_id) is None:
            raise NotFoundError("case not found")

    def _record(
        self,
        case_id: uuid.UUID,
        target_type: str,
        target_id: uuid.UUID,
        action: str,
        *,
        from_status: str | None = None,
        to_status: str | None = None,
        note: str | None = None,
        reviewer: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> ReviewAction:
        # Hash-chained, and attributed to the logged-in account when there is one.
        return record_action(
            self._db,
            case_id,
            target_type,
            target_id,
            action,
            from_status=from_status,
            to_status=to_status,
            note=note,
            reviewer=reviewer,
            payload=payload,
        )

    def _history(self, case_id: uuid.UUID, target_type: str, target_id: uuid.UUID) -> list:
        return [
            review_out(a)
            for a in self._repo.list_reviews(case_id, target_type=target_type, target_id=target_id)
        ]

    def _claims_out(self, rows: Sequence[ClaimRow]) -> list[ClaimOut]:
        ids = [c.id for c, _ev, _ex in rows]
        mentions: dict[uuid.UUID, list[MentionOut]] = {}
        for m, e in self._repo.mentions_for_claims(ids):
            mentions.setdefault(m.claim_id, []).append(
                MentionOut(
                    entity_id=e.id,
                    entity_type=e.entity_type,
                    display_name=e.display_name,
                    mention_text=m.mention_text,
                    role=m.role,
                )
            )
        counts: Counter[uuid.UUID] = Counter()
        if ids:
            for c in self._repo.list_contradictions(rows[0][0].case_id, claim_ids=ids):
                counts[c.claim_a_id] += 1
                counts[c.claim_b_id] += 1
        return [
            ClaimOut(
                id=c.id,
                case_id=c.case_id,
                evidence_id=c.evidence_id,
                evidence_name=ev.original_filename,
                evidence_type=ev.evidence_type,
                extraction_id=c.extraction_id,
                run_number=ex.run_number,
                source_current=bool(ex.is_current),
                segment_id=c.segment_id,
                analysis_run_id=c.analysis_run_id,
                claim_text=c.claim_text,
                claim_type=c.claim_type,
                subject=c.subject,
                predicate=c.predicate,
                predicate_key=c.predicate_key,
                object_value=c.object_value,
                event_time=c.event_time,
                location=c.location,
                quote=c.quote,
                quote_start=c.quote_start,
                quote_end=c.quote_end,
                locator=c.locator,
                modality=c.modality,
                grounding=c.grounding,  # type: ignore[arg-type]
                extraction_method=c.extraction_method,
                is_inferred=c.is_inferred,
                extraction_confidence=c.extraction_confidence,
                source_engine_confidence=c.source_engine_confidence,
                uncertainty=list(c.uncertainty or []),
                review_status=c.review_status,  # type: ignore[arg-type]
                reviewed_text=c.reviewed_text,
                review_note=c.review_note,
                reviewed_by=c.reviewed_by,
                reviewed_at=c.reviewed_at,
                created_at=c.created_at,
                entities=mentions.get(c.id, []),
                contradiction_count=counts.get(c.id, 0),
            )
            for c, ev, ex in rows
        ]

    def _briefs(self, case_id: uuid.UUID, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, ClaimBrief]:
        ids = list(set(ids))
        if not ids:
            return {}
        rows, _ = self._repo.list_claims(case_id, claim_ids=ids, current_only=False)
        return {c.id: brief(c, ev, bool(ex.is_current)) for c, ev, ex in rows}

    def _entity_outs(self, case_id: uuid.UUID, entities: Sequence[Entity]) -> list[EntityOut]:
        stats = self._repo.mention_stats(case_id)
        return [self._entity_out(e, stats) for e in entities]

    @staticmethod
    def _entity_out(entity: Entity, stats: dict[uuid.UUID, tuple[int, int]]) -> EntityOut:
        mentions, evidence = stats.get(entity.id, (0, 0))
        return EntityOut(
            id=entity.id,
            entity_type=entity.entity_type,
            display_name=entity.display_name,
            normalized_key=entity.normalized_key,
            aliases=list(entity.aliases or []),
            resolution_status=entity.resolution_status,  # type: ignore[arg-type]
            merged_into_id=entity.merged_into_id,
            review_status=entity.review_status,
            review_note=entity.review_note,
            mention_count=mentions,
            evidence_count=evidence,
            created_at=entity.created_at,
        )

    def _contradiction_outs(
        self, case_id: uuid.UUID, items: Sequence[PotentialContradiction]
    ) -> list[ContradictionOut]:
        briefs = self._briefs(
            case_id, [i.claim_a_id for i in items] + [i.claim_b_id for i in items]
        )
        alternatives: dict[uuid.UUID, list[AlternativeOut]] = {}
        for alt in self._repo.alternatives_for([i.id for i in items]):
            alternatives.setdefault(alt.contradiction_id, []).append(_alternative_out(alt))
        names = {e.id: e.display_name for e in self._repo.list_entities(case_id)} if items else {}
        event_ids = {i.via_event_id for i in items if i.via_event_id}
        events = {}
        if event_ids:
            from app.modules.analysis.models import Event

            events = {
                e.id: e
                for e in self._db.query(Event).filter(
                    Event.case_id == case_id, Event.id.in_(event_ids)
                )
            }
        out = []
        for item in items:
            a, b = briefs.get(item.claim_a_id), briefs.get(item.claim_b_id)
            if a is None or b is None:
                continue  # a finding must rest on existing claims; cascades make this rare
            out.append(
                ContradictionOut(
                    id=item.id,
                    category=item.category,
                    severity=item.severity,  # type: ignore[arg-type]
                    explanation=ExplanationOut(**item.explanation),
                    detection_confidence=item.detection_confidence,
                    uncertainty=list(item.uncertainty or []),
                    origin=item.origin,
                    review_status=item.review_status,  # type: ignore[arg-type]
                    reviewer_decision=item.reviewer_decision,
                    resolution_note=item.resolution_note,
                    linked_evidence_ids=[uuid.UUID(str(x)) for x in item.linked_evidence_ids or []],
                    via_entity_id=item.via_entity_id,
                    via_entity_name=names.get(item.via_entity_id) if item.via_entity_id else None,
                    via_event_id=item.via_event_id,
                    via_event_title=(
                        events[item.via_event_id].title if item.via_event_id in events else None
                    ),
                    via_event_status=(
                        events[item.via_event_id].status if item.via_event_id in events else None
                    ),
                    claim_a=a,
                    claim_b=b,
                    claims_current=a.source_current and b.source_current,
                    alternatives=alternatives.get(item.id, []),
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                )
            )
        return out

    def _relationship_outs(
        self, case_id: uuid.UUID, items: Sequence[ClaimRelationship]
    ) -> list[RelationshipOut]:
        briefs = self._briefs(
            case_id, [i.source_claim_id for i in items] + [i.target_claim_id for i in items]
        )
        names = {e.id: e.display_name for e in self._repo.list_entities(case_id)} if items else {}
        out = []
        for r in items:
            s, t = briefs.get(r.source_claim_id), briefs.get(r.target_claim_id)
            if s is None or t is None:
                continue
            out.append(
                RelationshipOut(
                    id=r.id,
                    relation_type=r.relation_type,
                    rationale=r.rationale,
                    origin=r.origin,
                    review_status=r.review_status,  # type: ignore[arg-type]
                    via_entity_id=r.via_entity_id,
                    via_entity_name=names.get(r.via_entity_id) if r.via_entity_id else None,
                    source_claim=s,
                    target_claim=t,
                    created_at=r.created_at,
                )
            )
        return out

    # --- analysis runs ----------------------------------------------------------

    def start_run(self, case_id: uuid.UUID, method: str) -> AnalysisRun:
        self._require_case(case_id)
        since = utcnow() - timedelta(minutes=self._settings.analysis_stale_minutes)
        if self._repo.active_run(case_id, since) is not None:
            raise ConflictError("an analysis of this case is already running")
        run = AnalysisRun(case_id=case_id, status="running", method=method, stats={})
        self._repo.add(run)
        self._db.commit()
        return run

    def latest_run(self, case_id: uuid.UUID) -> AnalysisRunState:
        self._require_case(case_id)
        run = self._repo.latest_run(case_id)
        return AnalysisRunState(run=run_out(run) if run else None)

    # --- claims -----------------------------------------------------------------

    def list_claims(
        self,
        case_id: uuid.UUID,
        *,
        evidence_id: uuid.UUID | None,
        review_status: str | None,
        claim_type: str | None,
        modality: str | None,
        entity_id: uuid.UUID | None,
        segment_id: uuid.UUID | None,
        search: str | None,
        include_superseded: bool,
        limit: int,
        offset: int,
    ) -> ClaimList:
        self._require_case(case_id)
        limit = max(1, min(limit, MAX_CLAIM_LIMIT))
        rows, total = self._repo.list_claims(
            case_id,
            evidence_id=evidence_id,
            review_status=[review_status] if review_status else None,
            claim_type=claim_type,
            modality=modality,
            entity_id=entity_id,
            segment_id=segment_id,
            search=search.strip() if search and search.strip() else None,
            current_only=not include_superseded,
            limit=limit,
            offset=max(0, offset),
        )
        return ClaimList(items=self._claims_out(rows), total=total, limit=limit, offset=offset)

    def get_claim(self, case_id: uuid.UUID, claim_id: uuid.UUID) -> ClaimDetail:
        self._require_case(case_id)
        row = self._repo.get_claim_row(case_id, claim_id)
        if row is None:
            raise NotFoundError("claim not found")
        (base,) = self._claims_out([row])
        claim = row[0]
        segment = self._repo.get_segment_any(claim.segment_id) if claim.segment_id else None
        rels = self._repo.list_relationships(case_id, claim_ids=[claim.id])
        conflicts = self._repo.list_contradictions(case_id, claim_ids=[claim.id])
        return ClaimDetail(
            **base.model_dump(),
            segment=_segment_ref(segment) if segment else None,
            relationships=self._relationship_outs(case_id, rels),
            contradiction_ids=[c.id for c in conflicts],
            history=self._history(case_id, "claim", claim.id),
        )

    def review_claim(
        self, case_id: uuid.UUID, claim_id: uuid.UUID, req: ClaimReviewRequest
    ) -> ClaimDetail:
        self._require_case(case_id)
        claim = self._repo.get_claim(case_id, claim_id)
        if claim is None:
            raise NotFoundError("claim not found")
        before = claim.review_status
        after = before
        payload: dict[str, Any] = {}
        if req.action in CLAIM_ACTIONS:
            after = CLAIM_ACTIONS[req.action]
            if after not in CLAIM_TRANSITIONS.get(before, set()):
                raise ConflictError(f"a claim cannot move from '{before}' to '{after}'")
            claim.review_status = after
        elif req.action == "edit":
            text = (req.reviewed_text or "").strip()
            if not text:
                raise BadRequestError("reviewed_text is required to edit a claim")
            payload = {"previous_reviewed_text": claim.reviewed_text, "reviewed_text": text}
            claim.reviewed_text = text  # claim_text and quote are never changed
        elif not (req.note or "").strip():
            raise BadRequestError("a note is required")
        if req.note:
            claim.review_note = req.note
        claim.reviewed_by = _who(req.reviewer)
        claim.reviewed_at = utcnow()
        self._record(
            case_id,
            "claim",
            claim.id,
            req.action,
            from_status=before,
            to_status=after,
            note=req.note,
            reviewer=req.reviewer,
            payload=payload,
        )
        self._db.commit()
        return self.get_claim(case_id, claim_id)

    # --- entities ---------------------------------------------------------------

    def list_entities(
        self,
        case_id: uuid.UUID,
        *,
        entity_type: str | None,
        search: str | None,
        include_merged: bool,
    ) -> EntityList:
        self._require_case(case_id)
        entities = self._repo.list_entities(case_id)
        if entity_type:
            entities = [e for e in entities if e.entity_type == entity_type]
        if not include_merged:
            entities = [e for e in entities if e.resolution_status != "merged"]
        if search and search.strip():
            needle = search.strip().lower()
            entities = [
                e
                for e in entities
                if needle in e.display_name.lower()
                or needle in e.normalized_key.lower()
                or any(needle in str(a).lower() for a in e.aliases or [])
            ]
        items = self._entity_outs(case_id, entities)
        items.sort(key=lambda e: (-e.evidence_count, -e.mention_count, e.display_name))
        return EntityList(items=items, total=len(items))

    def _candidates(self, case_id: uuid.UUID, focus: uuid.UUID | None = None) -> list[CandidateOut]:
        entities = [
            e
            for e in self._repo.list_entities(case_id)
            if e.resolution_status not in ("merged", "rejected")
        ]
        distinct: set[frozenset[uuid.UUID]] = set()
        for action in self._repo.list_reviews(
            case_id, target_type="entity", action="mark_distinct", limit=10_000
        ):
            other = action.payload.get("other_entity_id") if action.payload else None
            if other:
                distinct.add(frozenset({action.target_id, uuid.UUID(str(other))}))
        deferred: dict[frozenset[uuid.UUID], str | None] = {}
        for action in self._repo.list_reviews(
            case_id, target_type="entity", action="defer", limit=10_000
        ):
            other = action.payload.get("other_entity_id") if action.payload else None
            if other:
                deferred.setdefault(
                    frozenset({action.target_id, uuid.UUID(str(other))}), action.note
                )
        stats = self._repo.mention_stats(case_id)
        # Entities seen in OCR or speech output: only these can have been misread.
        machine_read = self._repo.entities_with_modalities(case_id, MACHINE_READ_MODALITIES)
        out: list[CandidateOut] = []
        for i, a in enumerate(entities):
            for b in entities[i + 1 :]:
                if focus is not None and focus not in (a.id, b.id):
                    continue
                if frozenset({a.id, b.id}) in distinct:
                    continue
                found = assess_candidate(
                    (a.entity_type, a.normalized_key, a.display_name),
                    (b.entity_type, b.normalized_key, b.display_name),
                    misreading_possible=a.id in machine_read or b.id in machine_read,
                )
                if found:
                    pair = frozenset({a.id, b.id})
                    out.append(
                        CandidateOut(
                            entity_a=self._entity_out(a, stats),
                            entity_b=self._entity_out(b, stats),
                            reason=found["reason"],
                            tier=found["tier"],
                            score=found["score"],
                            factors=found["factors"],
                            deferred=pair in deferred,
                            deferred_note=deferred.get(pair),
                        )
                    )
        out.sort(key=lambda c: (CANDIDATE_TIERS.index(c.tier), c.deferred))
        return out

    def candidates(self, case_id: uuid.UUID) -> CandidateList:
        self._require_case(case_id)
        items = self._candidates(case_id)
        return CandidateList(items=items, total=len(items))

    def get_entity(self, case_id: uuid.UUID, entity_id: uuid.UUID) -> EntityDetail:
        self._require_case(case_id)
        entity = self._repo.get_entity(case_id, entity_id)
        if entity is None:
            raise NotFoundError("entity not found")
        stats = self._repo.mention_stats(case_id)
        mentions = self._repo.mentions_for_entities(case_id, [entity.id])
        briefs = self._briefs(case_id, [m.claim_id for m in mentions])
        return EntityDetail(
            **self._entity_out(entity, stats).model_dump(),
            mentions=[
                EntityMentionOut(
                    claim_id=m.claim_id,
                    mention_text=m.mention_text,
                    role=m.role,
                    claim=briefs[m.claim_id],
                )
                for m in mentions
                if m.claim_id in briefs
            ],
            candidates=self._candidates(case_id, focus=entity.id),
            merged_from=[
                self._entity_out(e, stats)
                for e in self._repo.entities_merged_into(case_id, entity.id)
            ],
            history=self._history(case_id, "entity", entity.id),
        )

    def review_entity(
        self, case_id: uuid.UUID, entity_id: uuid.UUID, req: EntityReviewRequest
    ) -> EntityDetail:
        self._require_case(case_id)
        entity = self._repo.get_entity(case_id, entity_id)
        if entity is None:
            raise NotFoundError("entity not found")
        before = entity.resolution_status
        payload: dict[str, Any] = {}
        target: Entity | None = None
        if req.action in ("merge", "mark_distinct", "defer"):
            if req.target_entity_id is None:
                raise BadRequestError("target_entity_id is required")
            if req.target_entity_id == entity.id:
                raise BadRequestError("an entity cannot be compared with itself")
            target = self._repo.get_entity(case_id, req.target_entity_id)
            if target is None:
                raise NotFoundError("target entity not found")
        if req.action == "confirm":
            if before == "merged":
                raise ConflictError("a merged entity must be unmerged first")
            entity.resolution_status = "confirmed"
            entity.review_status = "verified"
        elif req.action == "reject":
            if before == "merged":
                raise ConflictError("a merged entity must be unmerged first")
            entity.resolution_status = "rejected"
            entity.review_status = "rejected"
        elif req.action == "merge":
            assert target is not None
            if before == "merged":
                raise ConflictError("this entity is already merged")
            if target.resolution_status in ("merged", "rejected"):
                raise ConflictError("cannot merge into a merged or rejected entity")
            entity.resolution_status = "merged"
            entity.merged_into_id = target.id
            # Mentions keep pointing at the original record; nothing is rewritten.
            added = [a for a in [entity.display_name, *entity.aliases] if a not in target.aliases]
            target.aliases = [*target.aliases, *added][:50]
            payload = {"target_entity_id": str(target.id), "aliases_added": added}
        elif req.action == "unmerge":
            if before != "merged":
                raise ConflictError("this entity is not merged")
            payload = {"previous_target_entity_id": str(entity.merged_into_id)}
            entity.resolution_status = "unresolved"
            entity.merged_into_id = None
        elif req.action == "mark_distinct":
            assert target is not None
            payload = {"other_entity_id": str(target.id)}
        elif req.action == "defer":
            assert target is not None
            if not (req.note or "").strip():
                raise BadRequestError("a note is required to defer a decision")
            payload = {"other_entity_id": str(target.id)}
        elif not (req.note or "").strip():
            raise BadRequestError("a note is required")
        if req.note:
            entity.review_note = req.note
        self._record(
            case_id,
            "entity",
            entity.id,
            req.action,
            from_status=before,
            to_status=entity.resolution_status,
            note=req.note,
            reviewer=req.reviewer,
            payload=payload,
        )
        self._db.commit()
        return self.get_entity(case_id, entity_id)

    # --- relationships ----------------------------------------------------------

    def list_relationships(
        self,
        case_id: uuid.UUID,
        *,
        relation_type: str | None,
        evidence_id: uuid.UUID | None,
        claim_id: uuid.UUID | None,
    ) -> RelationshipList:
        self._require_case(case_id)
        claim_ids: list[uuid.UUID] | None = None
        if claim_id is not None:
            claim_ids = [claim_id]
        elif evidence_id is not None:
            rows, _ = self._repo.list_claims(case_id, evidence_id=evidence_id, current_only=False)
            claim_ids = [c.id for c, _e, _x in rows]
        items = self._repo.list_relationships(
            case_id, claim_ids=claim_ids, relation_type=relation_type
        )
        out = self._relationship_outs(case_id, items)
        return RelationshipList(items=out, total=len(out))

    def review_relationship(
        self, case_id: uuid.UUID, relationship_id: uuid.UUID, req: RelationshipReviewRequest
    ) -> RelationshipOut:
        self._require_case(case_id)
        rel = self._repo.get_relationship(case_id, relationship_id)
        if rel is None:
            raise NotFoundError("relationship not found")
        before = after = rel.review_status
        if req.action in CLAIM_ACTIONS:
            after = CLAIM_ACTIONS[req.action]
            if after not in CLAIM_TRANSITIONS.get(before, set()):
                raise ConflictError(f"a relationship cannot move from '{before}' to '{after}'")
            rel.review_status = after
        elif not (req.note or "").strip():
            raise BadRequestError("a note is required")
        self._record(
            case_id,
            "relationship",
            rel.id,
            req.action,
            from_status=before,
            to_status=after,
            note=req.note,
            reviewer=req.reviewer,
        )
        self._db.commit()
        (out,) = self._relationship_outs(case_id, [rel])
        return out

    # --- contradictions ---------------------------------------------------------

    def list_contradictions(
        self,
        case_id: uuid.UUID,
        *,
        review_status: str | None,
        severity: str | None,
        evidence_id: uuid.UUID | None,
        entity_id: uuid.UUID | None,
    ) -> ContradictionList:
        self._require_case(case_id)
        claim_ids = None
        if evidence_id is not None:
            rows, _ = self._repo.list_claims(case_id, evidence_id=evidence_id, current_only=False)
            claim_ids = [c.id for c, _e, _x in rows]
        items = self._repo.list_contradictions(
            case_id,
            review_status=[review_status] if review_status else None,
            severity=severity,
            claim_ids=claim_ids,
            entity_id=entity_id,
        )
        out = self._contradiction_outs(case_id, items)
        return ContradictionList(items=out, total=len(out))

    def get_contradiction(
        self, case_id: uuid.UUID, contradiction_id: uuid.UUID
    ) -> ContradictionDetail:
        self._require_case(case_id)
        item = self._repo.get_contradiction(case_id, contradiction_id)
        if item is None:
            raise NotFoundError("potential contradiction not found")
        outs = self._contradiction_outs(case_id, [item])
        if not outs:
            raise NotFoundError("the claims of this potential contradiction no longer exist")
        return ContradictionDetail(
            **outs[0].model_dump(), history=self._history(case_id, "contradiction", item.id)
        )

    def review_contradiction(
        self, case_id: uuid.UUID, contradiction_id: uuid.UUID, req: ContradictionReviewRequest
    ) -> ContradictionDetail:
        self._require_case(case_id)
        item = self._repo.get_contradiction(case_id, contradiction_id)
        if item is None:
            raise NotFoundError("potential contradiction not found")
        before = after = item.review_status
        payload: dict[str, Any] = {}
        if req.action in CONTRADICTION_ACTIONS:
            after = CONTRADICTION_ACTIONS[req.action]
            if after not in CONTRADICTION_TRANSITIONS.get(before, set()):
                raise ConflictError(
                    f"a potential contradiction cannot move from '{before}' to '{after}'"
                )
            if req.action == "resolve":
                if not (req.note or "").strip():
                    raise BadRequestError("a resolution note is required")
                item.resolution_note = req.note
            item.review_status = after
            item.reviewer_decision = req.action
        elif req.action == "link_evidence":
            if req.evidence_id is None:
                raise BadRequestError("evidence_id is required")
            if self._repo.get_evidence(case_id, req.evidence_id) is None:
                raise NotFoundError("evidence not found")
            linked = [str(x) for x in item.linked_evidence_ids or []]
            if str(req.evidence_id) not in linked:
                item.linked_evidence_ids = [*linked, str(req.evidence_id)]
            payload = {"evidence_id": str(req.evidence_id)}
        elif not (req.note or "").strip():
            raise BadRequestError("a note is required")
        self._record(
            case_id,
            "contradiction",
            item.id,
            req.action,
            from_status=before,
            to_status=after,
            note=req.note,
            reviewer=req.reviewer,
            payload=payload,
        )
        self._db.commit()
        return self.get_contradiction(case_id, contradiction_id)

    def add_alternative(
        self, case_id: uuid.UUID, contradiction_id: uuid.UUID, req: AlternativeCreate
    ) -> ContradictionDetail:
        self._require_case(case_id)
        item = self._repo.get_contradiction(case_id, contradiction_id)
        if item is None:
            raise NotFoundError("potential contradiction not found")
        alt = AlternativeExplanation(
            case_id=case_id,
            contradiction_id=item.id,
            explanation=req.explanation.strip(),
            supporting_evidence=req.supporting_evidence,
            weakening_evidence=req.weakening_evidence,
            missing_information=req.missing_information,
            verification_recommendation=req.verification_recommendation,
            basis="human",
            author=_who(req.author),
        )
        self._repo.add(alt)
        self._repo.flush()
        self._record(
            case_id,
            "contradiction",
            item.id,
            "add_alternative",
            from_status=item.review_status,
            to_status=item.review_status,
            reviewer=req.author,
            payload={"alternative_id": str(alt.id)},
        )
        self._db.commit()
        return self.get_contradiction(case_id, contradiction_id)

    # --- history ----------------------------------------------------------------

    def reviews(
        self,
        case_id: uuid.UUID,
        *,
        target_type: str | None,
        target_id: uuid.UUID | None,
        limit: int,
    ) -> ReviewHistory:
        self._require_case(case_id)
        items = self._repo.list_reviews(
            case_id, target_type=target_type, target_id=target_id, limit=max(1, min(limit, 500))
        )
        return ReviewHistory(items=[review_out(a) for a in items], total=len(items))

    # --- segment corrections ----------------------------------------------------

    def _segment(
        self, case_id: uuid.UUID, evidence_id: uuid.UUID, segment_id: uuid.UUID
    ) -> ExtractionSegment:
        self._require_case(case_id)
        segment = self._repo.get_segment(case_id, evidence_id, segment_id)
        if segment is None:
            raise NotFoundError("segment not found")
        return segment

    def segment_reviews(
        self, case_id: uuid.UUID, evidence_id: uuid.UUID, segment_id: uuid.UUID
    ) -> SegmentReviewList:
        segment = self._segment(case_id, evidence_id, segment_id)
        items = [_segment_review_out(r) for r in self._repo.segment_reviews(segment.id)]
        return SegmentReviewList(original_text=segment.text, items=items, total=len(items))

    def add_segment_review(
        self,
        case_id: uuid.UUID,
        evidence_id: uuid.UUID,
        segment_id: uuid.UUID,
        req: SegmentReviewCreate,
    ) -> SegmentReviewList:
        segment = self._segment(case_id, evidence_id, segment_id)
        row = SegmentReview(
            case_id=case_id,
            evidence_id=evidence_id,
            segment_id=segment.id,
            corrected_text=req.corrected_text,
            note=req.note,
            reviewer=_who(req.reviewer),
        )
        self._repo.add(row)
        self._repo.flush()
        self._record(
            case_id,
            "segment",
            segment.id,
            "correct_text",
            note=req.note,
            reviewer=req.reviewer,
            payload={"segment_review_id": str(row.id)},
        )
        self._db.commit()
        return self.segment_reviews(case_id, evidence_id, segment_id)

    # --- review queue -----------------------------------------------------------

    def review_queue(self, case_id: uuid.UUID, *, limit: int = 50) -> ReviewQueueOut:
        self._require_case(case_id)
        rows, total_claims = self._repo.list_claims(case_id, review_status=OPEN_CLAIM_STATES)
        claims = self._claims_out(rows)

        def priority(c: ClaimOut) -> tuple:
            return (
                -c.contradiction_count,
                c.review_status != "needs_verification",
                c.grounding == "grounded",
                c.modality not in ("audio", "image"),
                c.source_engine_confidence if c.source_engine_confidence is not None else 1.0,
            )

        claims.sort(key=priority)
        open_items = self._repo.list_contradictions(
            case_id, review_status=OPEN_CONTRADICTION_STATES
        )
        contradictions = self._contradiction_outs(case_id, open_items)
        contradictions.sort(key=lambda c: ({"high": 0, "medium": 1, "low": 2}[c.severity],))
        candidates = self._candidates(case_id)
        return ReviewQueueOut(
            claims=claims[:limit],
            contradictions=contradictions[:limit],
            candidates=candidates[:limit],
            counts={
                "claims": total_claims,
                "contradictions": len(contradictions),
                "candidates": len(candidates),
                "total": total_claims + len(contradictions) + len(candidates),
            },
        )

    # --- knowledge graph --------------------------------------------------------

    def graph(
        self,
        case_id: uuid.UUID,
        *,
        include_claims: bool,
        entity_type: str | None,
        evidence_id: uuid.UUID | None,
        contradictions_only: bool,
        limit: int,
    ) -> GraphOut:
        self._require_case(case_id)
        limit = max(10, min(limit, 1000))
        rows, _ = self._repo.list_claims(case_id, evidence_id=evidence_id)
        rows = [r for r in rows if r[0].review_status != "rejected"]
        conflicts = [
            c for c in self._repo.list_contradictions(case_id) if c.review_status != "rejected"
        ]
        conflict_claims = {c.claim_a_id for c in conflicts} | {c.claim_b_id for c in conflicts}
        if contradictions_only:
            rows = [r for r in rows if r[0].id in conflict_claims]
        claim_ids = [r[0].id for r in rows]
        mention_pairs = self._repo.mentions_for_claims(claim_ids)
        entities = {
            e.id: e
            for e in self._repo.list_entities(case_id)
            if e.resolution_status not in ("rejected",)
        }

        def canonical(eid: uuid.UUID) -> uuid.UUID | None:
            e = entities.get(eid)
            hops = 0
            while e is not None and e.merged_into_id and hops < 10:
                e, hops = entities.get(e.merged_into_id), hops + 1
            return e.id if e is not None else None

        nodes: dict[str, GraphNode] = {}
        edges: dict[str, GraphEdge] = {}
        truncated = False

        def add_edge(source: str, target: str, kind: str, label: str | None = None) -> None:
            key = f"{kind}:{source}->{target}"
            if source in nodes and target in nodes and key not in edges:
                edges[key] = GraphEdge(id=key, source=source, target=target, kind=kind, label=label)

        evidence_seen: dict[uuid.UUID, Evidence] = {r[1].id: r[1] for r in rows}
        for ev in evidence_seen.values():
            nodes[f"evidence:{ev.id}"] = GraphNode(
                id=f"evidence:{ev.id}",
                kind="evidence",
                label=ev.original_filename,
                sublabel=ev.evidence_type,
                status=ev.processing_status,
                ref_id=ev.id,
                evidence_id=ev.id,
            )
        claim_entities: dict[uuid.UUID, set[uuid.UUID]] = {}
        stats = self._repo.mention_stats(case_id)
        for m, _e in mention_pairs:
            ent = canonical(m.entity_id)
            if ent is None:
                continue
            e = entities[ent]
            if entity_type and e.entity_type != entity_type:
                continue
            claim_entities.setdefault(m.claim_id, set()).add(ent)
            node_id = f"entity:{ent}"
            if node_id not in nodes:
                count = stats.get(ent, (0, 0))
                nodes[node_id] = GraphNode(
                    id=node_id,
                    kind="entity",
                    label=e.display_name,
                    sublabel=e.entity_type,
                    status=e.resolution_status,
                    ref_id=e.id,
                    data={"mentions": count[0], "evidence_count": count[1]},
                )
        if entity_type:
            rows = [r for r in rows if r[0].id in claim_entities]
        if include_claims:
            if len(rows) > limit:
                truncated = True
                rows = sorted(rows, key=lambda r: r[0].id not in conflict_claims)[:limit]
            for claim, ev, _ex in rows:
                node_id = f"claim:{claim.id}"
                nodes[node_id] = GraphNode(
                    id=node_id,
                    kind="claim",
                    label=_short(claim.claim_text),
                    sublabel=claim.modality,
                    status=claim.review_status,
                    ref_id=claim.id,
                    evidence_id=ev.id,
                    data={
                        "quote": claim.quote,
                        "locator": claim.locator,
                        "segment_id": str(claim.segment_id) if claim.segment_id else None,
                    },
                )
                add_edge(f"evidence:{ev.id}", node_id, "contains")
                for ent in claim_entities.get(claim.id, ()):
                    add_edge(node_id, f"entity:{ent}", "mentions")
        else:
            for claim, ev, _ex in rows:
                for ent in claim_entities.get(claim.id, ()):
                    add_edge(f"evidence:{ev.id}", f"entity:{ent}", "mentions")
        by_claim = {r[0].id: r for r in rows}
        for c in conflicts:
            if c.claim_a_id not in by_claim or c.claim_b_id not in by_claim:
                continue
            node_id = f"contradiction:{c.id}"
            nodes[node_id] = GraphNode(
                id=node_id,
                kind="contradiction",
                label=f"Potential {c.category} conflict",
                sublabel=c.severity,
                status=c.review_status,
                ref_id=c.id,
                data={"detection_confidence": c.detection_confidence},
            )
            for claim_id in (c.claim_a_id, c.claim_b_id):
                if include_claims:
                    add_edge(node_id, f"claim:{claim_id}", "conflicts")
                else:
                    add_edge(node_id, f"evidence:{by_claim[claim_id][1].id}", "conflicts")
        if include_claims:
            for r in self._repo.list_relationships(case_id, claim_ids=list(by_claim)):
                if r.relation_type == "potentially_conflicts_with" or r.review_status == "rejected":
                    continue
                add_edge(
                    f"claim:{r.source_claim_id}", f"claim:{r.target_claim_id}", r.relation_type
                )
        # Phase 2: proposed/confirmed events and the claims that are accounts of them.
        # Rejected events are left out; "status" tells confirmed from suggested.
        from app.modules.analysis.models import Event, EventClaim

        events = list(
            self._db.query(Event).filter(Event.case_id == case_id, Event.status != "rejected")
        )
        if events and not contradictions_only:
            members = self._db.query(EventClaim).filter(
                EventClaim.event_id.in_([e.id for e in events])
            )
            for e in events:
                nodes[f"event:{e.id}"] = GraphNode(
                    id=f"event:{e.id}",
                    kind="event",
                    label=e.title,
                    sublabel=e.event_type,
                    status=e.status,
                    ref_id=e.id,
                    data={
                        "association_confidence": e.association_confidence,
                        "link_basis": e.link_basis,
                        "date": e.event_date,
                    },
                )
            for m in members:
                if include_claims:
                    add_edge(
                        f"claim:{m.claim_id}", f"event:{m.event_id}", "account_of", m.account_label
                    )
                elif m.claim_id in by_claim:
                    add_edge(
                        f"evidence:{by_claim[m.claim_id][1].id}",
                        f"event:{m.event_id}",
                        "account_of",
                        m.account_label,
                    )
        counts = Counter(n.kind for n in nodes.values())
        return GraphOut(
            nodes=list(nodes.values()),
            edges=list(edges.values()),
            truncated=truncated,
            counts={**counts, "edges": len(edges)},
        )

    # --- dashboard and per-evidence summary -------------------------------------

    def dashboard(self, case_id: uuid.UUID, method: str) -> DashboardOut:
        self._require_case(case_id)
        evidence = self._repo.list_evidence(case_id)
        rows, total_claims = self._repo.list_claims(case_id)
        claims = [r[0] for r in rows]
        entities = [e for e in self._repo.list_entities(case_id) if e.resolution_status != "merged"]
        conflicts = self._repo.list_contradictions(case_id)
        candidates = self._candidates(case_id)
        open_claims = sum(1 for c in claims if c.review_status in OPEN_CLAIM_STATES)
        open_conflicts = sum(1 for c in conflicts if c.review_status in OPEN_CONTRADICTION_STATES)
        outs = self._entity_outs(case_id, entities)
        outs.sort(key=lambda e: (-e.evidence_count, -e.mention_count, e.display_name))
        run = self._repo.latest_run(case_id)
        return DashboardOut(
            evidence={
                "total": len(evidence),
                "by_type": dict(Counter(e.evidence_type for e in evidence)),
                "by_status": dict(Counter(e.processing_status for e in evidence)),
                "bytes": sum(e.byte_size for e in evidence),
            },
            segments=self._repo.segment_count(case_id),
            claims={
                "total": total_claims,
                "by_status": dict(Counter(c.review_status for c in claims)),
                "by_type": dict(Counter(c.claim_type for c in claims)),
                "by_modality": dict(Counter(c.modality for c in claims)),
                "insufficient_grounding": sum(1 for c in claims if c.grounding != "grounded"),
            },
            entities={
                "total": len(entities),
                "by_type": dict(Counter(e.entity_type for e in entities)),
                "candidates": len(candidates),
            },
            relationships=len(self._repo.list_relationships(case_id)),
            contradictions={
                "total": len(conflicts),
                "by_status": dict(Counter(c.review_status for c in conflicts)),
                "by_severity": dict(Counter(c.severity for c in conflicts)),
            },
            review_queue=open_claims + open_conflicts + len(candidates),
            latest_run=run_out(run) if run else None,
            recent_activity=[review_out(a) for a in self._repo.list_reviews(case_id, limit=12)],
            top_entities=outs[:10],
            claim_method=method,
        )

    def evidence_summary(
        self, case_id: uuid.UUID, evidence_id: uuid.UUID
    ) -> EvidenceAnalysisSummary:
        self._require_case(case_id)
        if self._repo.get_evidence(case_id, evidence_id) is None:
            raise NotFoundError("evidence not found")
        rows, total = self._repo.list_claims(case_id, evidence_id=evidence_id)
        ids = [r[0].id for r in rows]
        entity_ids = {m.entity_id for m, _e in self._repo.mentions_for_claims(ids)}
        rels = self._repo.list_relationships(case_id, claim_ids=ids) if ids else []
        conflicts = self._repo.list_contradictions(case_id, claim_ids=ids) if ids else []
        open_claims = sum(1 for r in rows if r[0].review_status in OPEN_CLAIM_STATES)
        open_conflicts = sum(1 for c in conflicts if c.review_status in OPEN_CONTRADICTION_STATES)
        return EvidenceAnalysisSummary(
            evidence_id=evidence_id,
            segments=self._repo.segment_count(case_id, evidence_id),
            claims=total,
            entities=len(entity_ids),
            relationships=len(rels),
            contradictions=len(conflicts),
            awaiting_review=open_claims + open_conflicts,
            analysed=total > 0 or self._repo.latest_run(case_id) is not None,
        )


def _short(text: str, n: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _segment_ref(segment: ExtractionSegment) -> SegmentRef:
    return SegmentRef(
        id=segment.id,
        extraction_id=segment.extraction_id,
        seq=segment.seq,
        segment_type=segment.segment_type,
        text=segment.text,
        locator=dict(segment.locator or {}),
        engine_confidence=segment.engine_confidence,
    )


def _alternative_out(alt: AlternativeExplanation) -> AlternativeOut:
    return AlternativeOut(
        id=alt.id,
        explanation=alt.explanation,
        supporting_evidence=alt.supporting_evidence,
        weakening_evidence=alt.weakening_evidence,
        missing_information=alt.missing_information,
        verification_recommendation=alt.verification_recommendation,
        basis=alt.basis,  # type: ignore[arg-type]
        status=alt.status,
        author=alt.author,
        created_at=alt.created_at,
    )


def _segment_review_out(row: SegmentReview) -> SegmentReviewOut:
    return SegmentReviewOut(
        id=row.id,
        segment_id=row.segment_id,
        evidence_id=row.evidence_id,
        corrected_text=row.corrected_text,
        note=row.note,
        reviewer=row.reviewer,
        created_at=row.created_at,
    )
