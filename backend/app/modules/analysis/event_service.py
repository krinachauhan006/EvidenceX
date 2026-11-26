"""Events and timeline: proposal persistence, reviewer decisions, event-gated
potential inconsistencies, and the chronological view.

The machine proposes; reviewers decide. Claims and their source anchors are never
edited here; event membership is a separate, audited layer on top of them.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db_types import utcnow
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.modules.analysis import events as ev
from app.modules.analysis.audit import record_action
from app.modules.analysis.engine import (
    ENGINE,
    ContradictionDraft,
    _interval,
    detect_in_event,
    detect_sequence,
)
from app.modules.analysis.models import (
    AlternativeExplanation,
    Claim,
    ClaimRelationship,
    Event,
    EventClaim,
    PotentialContradiction,
)
from app.modules.analysis.repository import AnalysisRepository
from app.modules.analysis.schemas_phase2 import (
    ComparisonOut,
    EventCreate,
    EventDetail,
    EventList,
    EventMemberOut,
    EventOut,
    EventReviewRequest,
    TimelineEventRef,
    TimelineGroup,
    TimelineItem,
    TimelineOut,
)
from app.modules.analysis.temporal import claim_date, document_date, tz_of
from app.modules.processing.models import Extraction, ExtractionSegment

EVENT_TRANSITIONS = {
    "proposed": {"confirmed", "rejected"},
    "confirmed": {"rejected", "proposed"},
    "rejected": {"proposed"},
}
ACTION_TARGET = {"confirm": "confirmed", "reject": "rejected", "reopen": "proposed"}


class EventService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = AnalysisRepository(db)

    # --- claim facts ------------------------------------------------------------

    def _evidence_context(self, case_id: uuid.UUID) -> tuple[dict, dict]:
        """Per evidence item: the single document date (if any) and the email date."""
        rows = self._db.execute(
            select(
                ExtractionSegment.evidence_id,
                ExtractionSegment.segment_type,
                ExtractionSegment.text,
                ExtractionSegment.data,
                ExtractionSegment.locator,
            )
            .join(Extraction, Extraction.id == ExtractionSegment.extraction_id)
            .where(ExtractionSegment.case_id == case_id, Extraction.is_current.is_(True))
        ).all()
        texts: dict[uuid.UUID, list[str]] = defaultdict(list)
        email_dates: dict[uuid.UUID, str] = {}
        for evidence_id, stype, text, data, locator in rows:
            if stype == "email_header" and str((locator or {}).get("name", "")).lower() == "date":
                iso = (data or {}).get("date_iso")
                if iso:
                    email_dates[evidence_id] = str(iso)
                continue
            if text:
                texts[evidence_id].append(text)
        return {k: document_date(v) for k, v in texts.items()}, email_dates

    def claim_infos(
        self, case_id: uuid.UUID, claim_ids: list[uuid.UUID] | None = None
    ) -> dict[uuid.UUID, ev.ClaimInfo]:
        rows, _ = self._repo.list_claims(case_id, claim_ids=claim_ids)
        rows = [
            r
            for r in rows
            if r[0].review_status != "rejected" and r[0].superseded_by_run_id is None
        ]
        doc_dates, email_dates = self._evidence_context(case_id)
        entities = {e.id: e for e in self._repo.list_entities(case_id)}

        def canonical(eid: uuid.UUID) -> uuid.UUID | None:
            e, hops = entities.get(eid), 0
            while e is not None and e.merged_into_id and hops < 10:
                e, hops = entities.get(e.merged_into_id), hops + 1
            if e is None or e.resolution_status == "rejected":
                return None
            return e.id

        mentions: dict[uuid.UUID, list[tuple[str, str, str, str]]] = defaultdict(list)
        for m, _e in self._repo.mentions_for_claims([r[0].id for r in rows]):
            cid = canonical(m.entity_id)
            if cid is not None:
                e = entities[cid]
                mentions[m.claim_id].append(
                    (e.entity_type, e.normalized_key, e.display_name, str(e.id))
                )
        out: dict[uuid.UUID, ev.ClaimInfo] = {}
        for claim, evidence, _ex in rows:
            t = claim.event_time or {}
            if t.get("kind") == "datetime" and claim.predicate_key == "email_sent":
                continue  # the message's own send time is metadata, not an event account
            reading = claim_date(
                claim.quote,
                email_date_iso=email_dates.get(evidence.id)
                if evidence.evidence_type == "email"
                else None,
                doc_date=doc_dates.get(evidence.id),
            )
            interval = _interval(t) if t.get("kind") != "datetime" else None
            out[claim.id] = ev.ClaimInfo(
                id=str(claim.id),
                evidence_id=str(evidence.id),
                evidence_name=evidence.original_filename,
                modality=claim.modality,
                quote=claim.quote,
                predicate_key=claim.predicate_key,
                interval=interval,
                time_raw=t.get("raw"),
                time_precision=t.get("precision"),
                date=reading.value,
                date_precision=reading.precision,
                date_source=reading.source,
                tz=tz_of(t)
                or (
                    tz_of({"value": email_dates.get(evidence.id)})
                    if evidence.evidence_type == "email"
                    else None
                ),
                uncertainty=list(claim.uncertainty or []),
                entities=mentions.get(claim.id, []),
            )
        return out

    # --- proposals ----------------------------------------------------------------

    def propose(self, case_id: uuid.UUID) -> int:
        """Persist new rule-based proposals. Existing events (including rejected ones)
        with the same signature are never re-proposed. Returns the number created."""
        infos = self.claim_infos(case_id)
        existing = set(self._db.scalars(select(Event.signature).where(Event.case_id == case_id)))
        made = 0
        for p in ev.propose_events(list(infos.values())):
            if p.signature in existing:
                continue
            event = Event(
                case_id=case_id,
                event_type=p.event_type,
                title=p.title,
                anchor_kind=p.anchor_kind,
                anchor_key=p.anchor_key,
                anchor_entity_id=uuid.UUID(p.anchor_entity_id) if p.anchor_entity_id else None,
                event_date=p.event_date,
                date_precision=p.date_precision,
                link_basis=p.link_basis,
                association_confidence=p.association_confidence,
                factors=p.factors,
                missing_links=p.missing_links,
                origin=ev_origin(),
                status="proposed",
                signature=p.signature,
            )
            self._db.add(event)
            self._db.flush()
            for m in p.members:
                self._db.add(
                    EventClaim(
                        case_id=case_id,
                        event_id=event.id,
                        claim_id=uuid.UUID(m.claim.id),
                        account_label=m.account_label,
                        attribution=m.attribution,
                        match_reasons=m.reasons,
                        added_by="system",
                    )
                )
            made += 1
        self._db.flush()
        return made

    # --- reads --------------------------------------------------------------------

    def _event(self, case_id: uuid.UUID, event_id: uuid.UUID) -> Event:
        event = self._db.scalar(select(Event).where(Event.id == event_id, Event.case_id == case_id))
        if event is None:
            raise NotFoundError("event not found")
        return event

    def _members(self, events: list[Event]) -> dict[uuid.UUID, list[EventClaim]]:
        out: dict[uuid.UUID, list[EventClaim]] = defaultdict(list)
        if events:
            for row in self._db.scalars(
                select(EventClaim)
                .where(EventClaim.event_id.in_([e.id for e in events]))
                .order_by(EventClaim.created_at, EventClaim.id)
            ):
                out[row.event_id].append(row)
        return out

    def _member_objects(
        self, rows: list[EventClaim], infos: dict[uuid.UUID, ev.ClaimInfo]
    ) -> list[ev.Member]:
        return [
            ev.Member(infos[r.claim_id], r.attribution, r.account_label, list(r.match_reasons))
            for r in rows
            if r.claim_id in infos
        ]

    def _outs(self, case_id: uuid.UUID, events: list[Event]) -> list[EventOut]:
        from app.modules.analysis.service import AnalysisService

        members = self._members(events)
        claim_ids = sorted({r.claim_id for rows in members.values() for r in rows}, key=str)
        infos = self.claim_infos(case_id, claim_ids) if claim_ids else {}
        briefs = AnalysisService(self._db)._briefs(case_id, claim_ids) if claim_ids else {}
        conflicts: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for c in self._db.scalars(
            select(PotentialContradiction).where(
                PotentialContradiction.case_id == case_id,
                PotentialContradiction.via_event_id.in_([e.id for e in events]),
            )
        ):
            conflicts[c.via_event_id].append(c.id)
        out = []
        for e in events:
            rows = [r for r in members.get(e.id, []) if r.claim_id in briefs]
            objs = self._member_objects(rows, infos)
            out.append(
                EventOut(
                    id=e.id,
                    event_type=e.event_type,
                    title=e.title,
                    anchor_kind=e.anchor_kind,
                    anchor_key=e.anchor_key,
                    event_date=e.event_date,
                    date_precision=e.date_precision,
                    link_basis=e.link_basis,
                    association_confidence=e.association_confidence,
                    factors=list(e.factors or []),
                    missing_links=list(e.missing_links or []),
                    origin=e.origin,
                    status=e.status,  # type: ignore[arg-type]
                    review_note=e.review_note,
                    reviewed_by=e.reviewed_by,
                    reviewed_at=e.reviewed_at,
                    created_at=e.created_at,
                    members=[
                        EventMemberOut(
                            claim=briefs[r.claim_id],
                            account_label=r.account_label,
                            attribution=r.attribution,
                            match_reasons=list(r.match_reasons or []),
                            added_by=r.added_by,
                            date=infos[r.claim_id].date if r.claim_id in infos else None,
                            date_precision=(
                                infos[r.claim_id].date_precision
                                if r.claim_id in infos
                                else "unknown"
                            ),
                            date_source=infos[r.claim_id].date_source
                            if r.claim_id in infos
                            else None,
                        )
                        for r in rows
                    ],
                    comparisons=[
                        ComparisonOut(
                            claim_a_id=uuid.UUID(c.a.claim.id),
                            claim_b_id=uuid.UUID(c.b.claim.id),
                            account_a=c.a.account_label,
                            account_b=c.b.account_label,
                            classification=c.classification,
                            gap_minutes=c.gap_minutes,
                            explanation=c.explanation,
                            is_candidate=c.is_candidate,
                        )
                        for c in ev.compare_accounts(objs)
                    ],
                    contradiction_ids=conflicts.get(e.id, []),
                )
            )
        return out

    def list_events(
        self, case_id: uuid.UUID, *, status: str | None = None, event_type: str | None = None
    ) -> EventList:
        stmt = select(Event).where(Event.case_id == case_id)
        if status:
            stmt = stmt.where(Event.status == status)
        if event_type:
            stmt = stmt.where(Event.event_type == event_type)
        events = list(self._db.scalars(stmt.order_by(Event.event_date, Event.created_at)))
        items = self._outs(case_id, events)
        return EventList(items=items, total=len(items))

    def get_event(self, case_id: uuid.UUID, event_id: uuid.UUID) -> EventDetail:
        from app.modules.analysis.service import review_out

        event = self._event(case_id, event_id)
        (out,) = self._outs(case_id, [event])
        history = [
            review_out(a)
            for a in self._repo.list_reviews(case_id, target_type="event", target_id=event.id)
        ]
        return EventDetail(**out.model_dump(), history=history)

    # --- reviewer actions -----------------------------------------------------------

    def _check_claims(self, case_id: uuid.UUID, ids: list[uuid.UUID]) -> list[Claim]:
        claims = list(
            self._db.scalars(select(Claim).where(Claim.case_id == case_id, Claim.id.in_(ids)))
        )
        if len(claims) != len(set(ids)):
            raise NotFoundError("one or more claims were not found in this case")
        return claims

    def create_event(self, case_id: uuid.UUID, req: EventCreate) -> EventDetail:
        self._check_claims(case_id, req.claim_ids)
        infos = self.claim_infos(case_id, req.claim_ids)
        dates = {i.date for i in infos.values() if i.date}
        sig = hashlib.sha256(
            (
                "reviewer|" + "|".join(sorted(map(str, req.claim_ids))) + "|" + str(uuid.uuid4())
            ).encode()
        ).hexdigest()
        event = Event(
            case_id=case_id,
            event_type=req.event_type,
            title=req.title.strip(),
            anchor_kind="reviewer",
            anchor_key="-",
            event_date=next(iter(dates)) if len(dates) == 1 else None,
            date_precision="day" if len(dates) == 1 else "unknown",
            link_basis="reviewer",
            association_confidence=0.5,
            factors=[
                {
                    "factor": "grouped by a reviewer",
                    "effect": 0.5,
                    "detail": "no rule score; the reviewer's judgement defines the group",
                }
            ],
            missing_links=[],
            origin="reviewer",
            status="proposed",
            signature=sig,
        )
        self._db.add(event)
        self._db.flush()
        for cid in req.claim_ids:
            info = infos.get(cid)
            attr = ev.attribution_of(info.quote) if info else None
            self._db.add(
                EventClaim(
                    case_id=case_id,
                    event_id=event.id,
                    claim_id=cid,
                    account_label=ev.account_label(info, attr) if info else str(cid),
                    attribution=attr,
                    match_reasons=["added by a reviewer"],
                    added_by="reviewer",
                )
            )
        record_action(
            self._db,
            case_id,
            "event",
            event.id,
            "create",
            to_status="proposed",
            note=req.note,
            payload={"claim_ids": [str(c) for c in req.claim_ids]},
        )
        self._db.commit()
        return self.get_event(case_id, event.id)

    def review(
        self, case_id: uuid.UUID, event_id: uuid.UUID, req: EventReviewRequest
    ) -> EventDetail:
        event = self._event(case_id, event_id)
        before = event.status
        payload: dict[str, Any] = {}
        new_event_id: uuid.UUID | None = None
        if req.action in ACTION_TARGET:
            after = ACTION_TARGET[req.action]
            if after not in EVENT_TRANSITIONS.get(before, set()):
                raise ConflictError(f"an event cannot move from '{before}' to '{after}'")
            event.status = after
            event.reviewed_at = utcnow()
            from app.modules.analysis.service import _who

            event.reviewed_by = _who(req.reviewer)
            if req.note:
                event.review_note = req.note
        elif req.action == "add_claim":
            if req.claim_id is None:
                raise BadRequestError("claim_id is required")
            self._check_claims(case_id, [req.claim_id])
            if self._db.scalar(
                select(EventClaim.id).where(
                    EventClaim.event_id == event.id, EventClaim.claim_id == req.claim_id
                )
            ):
                raise ConflictError("the claim is already part of this event")
            info = self.claim_infos(case_id, [req.claim_id]).get(req.claim_id)
            attr = ev.attribution_of(info.quote) if info else None
            self._db.add(
                EventClaim(
                    case_id=case_id,
                    event_id=event.id,
                    claim_id=req.claim_id,
                    account_label=ev.account_label(info, attr) if info else str(req.claim_id),
                    attribution=attr,
                    match_reasons=["added by a reviewer"],
                    added_by="reviewer",
                )
            )
            payload = {"claim_id": str(req.claim_id)}
        elif req.action == "remove_claim":
            row = self._db.scalar(
                select(EventClaim).where(
                    EventClaim.event_id == event.id, EventClaim.claim_id == req.claim_id
                )
            )
            if row is None:
                raise NotFoundError("the claim is not part of this event")
            self._db.delete(row)
            payload = {"claim_id": str(req.claim_id)}
        elif req.action == "split":
            ids = list(dict.fromkeys(req.claim_ids))
            rows = list(
                self._db.scalars(
                    select(EventClaim).where(
                        EventClaim.event_id == event.id, EventClaim.claim_id.in_(ids)
                    )
                )
            )
            remaining = self._db.scalar(
                select(EventClaim.id).where(
                    EventClaim.event_id == event.id, EventClaim.claim_id.not_in(ids)
                )
            )
            if not ids or len(rows) != len(ids) or remaining is None:
                raise BadRequestError(
                    "choose some, but not all, of this event's claims to split off"
                )
            new = Event(
                case_id=case_id,
                event_type=event.event_type,
                title=f"{event.title} (split)",
                anchor_kind=event.anchor_kind,
                anchor_key=event.anchor_key,
                anchor_entity_id=event.anchor_entity_id,
                event_date=event.event_date,
                date_precision=event.date_precision,
                link_basis="reviewer",
                association_confidence=event.association_confidence,
                factors=[*event.factors, {"factor": "split by a reviewer", "effect": 0}],
                missing_links=list(event.missing_links),
                origin="reviewer",
                status="proposed",
                signature=hashlib.sha256(f"split|{event.id}|{uuid.uuid4()}".encode()).hexdigest(),
            )
            self._db.add(new)
            self._db.flush()
            for r in rows:
                r.event_id = new.id  # the membership moves; the claim itself is untouched
            new_event_id = new.id
            payload = {"claim_ids": [str(i) for i in ids], "new_event_id": str(new.id)}
        elif not (req.note or "").strip():
            raise BadRequestError("a note is required")
        else:
            event.review_note = req.note
        record_action(
            self._db,
            case_id,
            "event",
            event.id,
            req.action,
            from_status=before,
            to_status=event.status,
            note=req.note,
            reviewer=req.reviewer,
            payload=payload,
        )
        self._db.flush()
        if event.status == "confirmed" and req.action in ("confirm", "add_claim"):
            created = self.detect_for_event(case_id, event)
            if created:
                record_action(
                    self._db,
                    case_id,
                    "event",
                    event.id,
                    "detect",
                    payload={"potential_inconsistencies_created": created, "engine": ENGINE},
                )
        self._db.commit()
        if new_event_id is not None:
            record_action(
                self._db,
                case_id,
                "event",
                new_event_id,
                "create",
                to_status="proposed",
                payload={"split_from": str(event.id)},
            )
            self._db.commit()
        return self.get_event(case_id, event.id)

    # --- event-gated detection --------------------------------------------------------

    def _persist(self, case_id: uuid.UUID, draft: ContradictionDraft, event: Event) -> bool:
        a, b = uuid.UUID(draft.claim_a_id), uuid.UUID(draft.claim_b_id)
        if self._repo.contradiction_exists(a, b, draft.category):
            return False
        record = PotentialContradiction(
            case_id=case_id,
            claim_a_id=a,
            claim_b_id=b,
            via_entity_id=event.anchor_entity_id,
            via_event_id=event.id,
            category=draft.category,
            explanation=draft.explanation,
            severity=draft.severity,
            detection_confidence=draft.detection_confidence,
            uncertainty=draft.uncertainty,
            origin=f"{draft.origin}_event",
            linked_evidence_ids=[],
        )
        self._db.add(record)
        self._db.flush()
        for alt in draft.alternatives:
            self._db.add(
                AlternativeExplanation(
                    case_id=case_id,
                    contradiction_id=record.id,
                    explanation=alt.explanation,
                    supporting_evidence=alt.supporting_evidence,
                    weakening_evidence=alt.weakening_evidence,
                    missing_information=alt.missing_information,
                    verification_recommendation=alt.verification_recommendation,
                    basis=alt.basis,
                )
            )
        if not self._repo.relationship_exists(a, b, "potentially_conflicts_with"):
            self._db.add(
                ClaimRelationship(
                    case_id=case_id,
                    source_claim_id=a,
                    target_claim_id=b,
                    via_entity_id=event.anchor_entity_id,
                    relation_type="potentially_conflicts_with",
                    rationale=draft.explanation["why"],
                    origin=f"{draft.origin}_event",
                )
            )
        self._db.flush()
        return True

    def detect_for_event(self, case_id: uuid.UUID, event: Event) -> int:
        rows = self._members([event])[event.id]
        infos = self.claim_infos(case_id, [r.claim_id for r in rows])
        members = self._member_objects(rows, infos)
        drafts = detect_in_event(
            event_title=event.title,
            link_basis=event.link_basis,
            missing_links=list(event.missing_links or []),
            comparisons=ev.compare_accounts(members),
        )
        made = sum(self._persist(case_id, d, event) for d in drafts)
        # Order conflicts against the other confirmed events with the same anchor/date.
        confirmed = list(
            self._db.scalars(
                select(Event).where(
                    Event.case_id == case_id,
                    Event.status == "confirmed",
                    Event.anchor_kind == event.anchor_kind,
                    Event.anchor_key == event.anchor_key,
                )
            )
        )
        if len(confirmed) > 1:
            all_rows = self._members(confirmed)
            all_infos = self.claim_infos(
                case_id, [r.claim_id for rs in all_rows.values() for r in rs]
            )
            seq = ev.sequence_conflicts(
                [
                    (
                        e.event_type,
                        e.anchor_kind,
                        e.anchor_key,
                        e.event_date,
                        self._member_objects(all_rows[e.id], all_infos),
                    )
                    for e in confirmed
                ]
            )
            for draft in detect_sequence(seq, event.link_basis):
                made += self._persist(case_id, draft, event)
        return made

    # --- timeline -------------------------------------------------------------------

    def timeline(
        self,
        case_id: uuid.UUID,
        *,
        evidence_id: uuid.UUID | None = None,
        entity_id: uuid.UUID | None = None,
        event_id: uuid.UUID | None = None,
        review_status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        modality: str | None = None,
    ) -> TimelineOut:
        from app.modules.analysis.service import AnalysisService

        infos = self.claim_infos(case_id)
        timed = {cid: i for cid, i in infos.items() if i.time_raw or i.date}
        events = list(self._db.scalars(select(Event).where(Event.case_id == case_id)))
        members = self._members(events)
        by_claim: dict[uuid.UUID, list[TimelineEventRef]] = defaultdict(list)
        for e in events:
            for r in members.get(e.id, []):
                by_claim[r.claim_id].append(
                    TimelineEventRef(id=e.id, title=e.title, status=e.status)
                )  # type: ignore[arg-type]
        conflicts: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for c in self._repo.list_contradictions(case_id):
            if c.review_status != "rejected":
                conflicts[c.claim_a_id].append(c.id)
                conflicts[c.claim_b_id].append(c.id)
        allowed: set[uuid.UUID] | None = None
        if entity_id is not None:
            rows, _ = self._repo.list_claims(case_id, entity_id=entity_id)
            allowed = {r[0].id for r in rows}
        briefs = AnalysisService(self._db)._briefs(case_id, list(timed))
        items: list[TimelineItem] = []
        for cid, i in timed.items():
            b = briefs.get(cid)
            if b is None:
                continue
            if evidence_id and str(evidence_id) != i.evidence_id:
                continue
            if modality and i.modality != modality:
                continue
            if review_status and b.review_status != review_status:
                continue
            if allowed is not None and cid not in allowed:
                continue
            if event_id and all(r.id != event_id for r in by_claim.get(cid, [])):
                continue
            if date_from and (not i.date or i.date < date_from):
                continue
            if date_to and (not i.date or i.date > date_to):
                continue
            items.append(
                TimelineItem(
                    claim=b,
                    date=i.date,
                    date_precision=i.date_precision,
                    date_source=i.date_source,
                    time_raw=i.time_raw,
                    time_precision=i.time_precision,
                    start_minute=i.interval[0] if i.interval else None,
                    end_minute=i.interval[1] if i.interval else None,
                    tz=i.tz,
                    events=by_claim.get(cid, []),
                    contradiction_ids=conflicts.get(cid, []),
                )
            )
        groups: dict[str | None, list[TimelineItem]] = defaultdict(list)
        for it in items:
            groups[it.date].append(it)
        ordered = sorted((d for d in groups if d), key=str)
        out = [
            TimelineGroup(
                date=d,
                items=sorted(
                    groups[d], key=lambda x: (x.start_minute is None, x.start_minute or 0)
                ),
            )
            for d in ordered
        ]
        if None in groups:
            out.append(
                TimelineGroup(
                    date=None,
                    items=sorted(
                        groups[None], key=lambda x: (x.start_minute is None, x.start_minute or 0)
                    ),
                )
            )
        return TimelineOut(
            groups=out,
            total=len(items),
            undated_note=(
                "Items without a stated or inherited date are listed under "
                "'Date not stated'. They are never placed on a guessed day."
            ),
        )


def ev_origin() -> str:
    return "rule_based_events_v1"
