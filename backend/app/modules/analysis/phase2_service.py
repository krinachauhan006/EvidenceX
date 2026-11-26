"""Search, grounded Q&A, report generation and graph exports for one case."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.actor import current_actor
from app.core.config import Settings, get_settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.logging import get_logger
from app.modules.analysis import search as srch
from app.modules.analysis.audit import record_action
from app.modules.analysis.models import Claim, Entity, Event, Report
from app.modules.analysis.report_text import cite
from app.modules.analysis.schemas_phase2 import (
    AskCitation,
    AskOut,
    AskStatement,
    ReportCreate,
    ReportList,
    ReportOut,
    SearchHit,
    SearchOut,
)
from app.modules.cases.models import Case
from app.modules.evidence.models import Evidence
from app.modules.processing.models import Extraction, ExtractionSegment

logger = get_logger(__name__)


def _ai_client(settings: Settings, case: Case):  # noqa: ANN202
    """A Gemini client when configured AND allowed for the case, else None."""
    if not (
        settings.gemini_api_key
        and case.ai_processing_allowed
        and settings.claim_extractor in ("gemini", "hybrid")
    ):
        return None
    from app.ai.gemini_client import GeminiClient

    return GeminiClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        timeout_seconds=settings.gemini_timeout_seconds,
    )


class Phase2Service:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self._db = db
        self._settings = settings or get_settings()

    def _case(self, case_id: uuid.UUID) -> Case:
        case = self._db.get(Case, case_id)
        if case is None:
            raise NotFoundError("case not found")
        return case

    # --- search ---------------------------------------------------------------

    def _docs(self, case_id: uuid.UUID, kinds: set[str]) -> list[srch.Doc]:
        docs: list[srch.Doc] = []
        ev = {
            e.id: e for e in self._db.scalars(select(Evidence).where(Evidence.case_id == case_id))
        }
        if "segment" in kinds:
            rows = self._db.execute(
                select(ExtractionSegment)
                .join(Extraction, Extraction.id == ExtractionSegment.extraction_id)
                .where(
                    ExtractionSegment.case_id == case_id,
                    Extraction.is_current.is_(True),
                    ExtractionSegment.text.is_not(None),
                )
            ).scalars()
            for s in rows:
                e = ev.get(s.evidence_id)
                docs.append(
                    srch.Doc(
                        "segment",
                        str(s.id),
                        s.text or "",
                        e.original_filename if e else "",
                        {
                            "evidence_id": s.evidence_id,
                            "evidence_name": e.original_filename if e else None,
                            "modality": e.evidence_type if e else None,
                            "segment_id": s.id,
                            "locator": s.locator,
                            "confidence": s.engine_confidence,
                            "segment_type": s.segment_type,
                        },
                    )
                )
        if "claim" in kinds:
            for c in self._db.scalars(
                select(Claim).where(Claim.case_id == case_id, Claim.superseded_by_run_id.is_(None))
            ):
                e = ev.get(c.evidence_id)
                docs.append(
                    srch.Doc(
                        "claim",
                        str(c.id),
                        f"{c.claim_text} {c.quote}",
                        c.claim_type,
                        {
                            "evidence_id": c.evidence_id,
                            "evidence_name": e.original_filename if e else None,
                            "modality": c.modality,
                            "segment_id": c.segment_id,
                            "claim_id": c.id,
                            "locator": c.locator,
                            "review_status": c.review_status,
                            "confidence": c.extraction_confidence,
                            "quote": c.quote,
                            "date": (c.event_time or {}).get("date_raw"),
                        },
                    )
                )
        if "entity" in kinds:
            for en in self._db.scalars(
                select(Entity).where(
                    Entity.case_id == case_id, Entity.resolution_status != "merged"
                )
            ):
                docs.append(
                    srch.Doc(
                        "entity",
                        str(en.id),
                        " ".join([en.display_name, en.normalized_key, *(en.aliases or [])]),
                        en.entity_type,
                        {"review_status": en.resolution_status},
                    )
                )
        if "event" in kinds:
            for evn in self._db.scalars(select(Event).where(Event.case_id == case_id)):
                docs.append(
                    srch.Doc(
                        "event",
                        str(evn.id),
                        evn.title,
                        evn.event_type,
                        {"review_status": evn.status, "date": evn.event_date},
                    )
                )
        return docs

    def search(
        self,
        case_id: uuid.UUID,
        q: str,
        *,
        kinds: set[str] | None = None,
        evidence_id: uuid.UUID | None = None,
        modality: str | None = None,
        review_status: str | None = None,
        min_confidence: float | None = None,
        entity_id: uuid.UUID | None = None,
        event_id: uuid.UUID | None = None,
        limit: int = 30,
    ) -> SearchOut:
        self._case(case_id)
        q = (q or "").strip()
        if not q:
            raise BadRequestError("enter a search query")
        docs = self._docs(case_id, kinds or {"segment", "claim", "entity", "event"})
        allowed_claims: set[uuid.UUID] | None = None
        if entity_id or event_id:
            from app.modules.analysis.models import ClaimEntity, EventClaim

            stmt = (
                select(ClaimEntity.claim_id).where(ClaimEntity.entity_id == entity_id)
                if entity_id
                else select(EventClaim.claim_id).where(EventClaim.event_id == event_id)
            )
            allowed_claims = set(self._db.scalars(stmt))

        def keep(d: srch.Doc) -> bool:
            m = d.meta
            if evidence_id and m.get("evidence_id") != evidence_id:
                return False
            if modality and m.get("modality") != modality:
                return False
            if review_status and m.get("review_status") != review_status:
                return False
            if min_confidence is not None and (
                m.get("confidence") is None or m["confidence"] < min_confidence
            ):
                return False
            if allowed_claims is not None and m.get("claim_id") not in allowed_claims:
                return False
            return True

        hits, expanded = srch.rank([d for d in docs if keep(d)], q, limit=max(1, min(limit, 100)))
        items = []
        for h in hits:
            m = h.doc.meta
            title = {
                "segment": f"{m.get('evidence_name')} · {m.get('segment_type')}",
                "claim": f"Claim in {m.get('evidence_name')}",
                "entity": f"Entity ({h.doc.title})",
                "event": f"Event ({h.doc.title})",
            }[h.doc.kind]
            items.append(
                SearchHit(
                    kind=h.doc.kind,
                    id=uuid.UUID(h.doc.id),
                    evidence_id=m.get("evidence_id"),
                    evidence_name=m.get("evidence_name"),
                    segment_id=m.get("segment_id"),
                    claim_id=m.get("claim_id"),
                    title=title,
                    excerpt=srch.excerpt(m.get("quote") or h.doc.text, h.matched),
                    locator=m.get("locator"),
                    score=h.score,
                    matched=h.matched,
                    why=h.why,
                    review_status=m.get("review_status"),
                    modality=m.get("modality"),
                )
            )
        return SearchOut(
            query=q,
            expanded_terms=expanded,
            method=srch.METHOD_LABEL,
            items=items,
            total=len(items),
        )

    # --- grounded Q&A -------------------------------------------------------------

    def ask(self, case_id: uuid.UUID, question: str) -> AskOut:
        case = self._case(case_id)
        found = self.search(case_id, question, kinds={"claim", "segment"}, limit=8).items
        sources, citations = [], []
        for i, h in enumerate(found, 1):
            ref = f"S{i}"
            where = cite(h.evidence_name or "?", h.locator)
            sources.append({"ref": ref, "text": h.excerpt, "where": where})
            citations.append(
                AskCitation(
                    ref=ref,
                    kind=h.kind,
                    id=h.id,
                    evidence_name=h.evidence_name,
                    locator=h.locator,
                    excerpt=h.excerpt,
                )
            )
        client = _ai_client(self._settings, case)
        if client is not None and sources:
            from app.ai.gemini_client import AIError
            from app.ai.qa import ask as ai_ask

            try:
                statements, removed = ai_ask(client, question, sources)
                return AskOut(
                    question=question,
                    method=f"gemini ({self._settings.gemini_model}) + local citation check",
                    answer=[AskStatement(**s) for s in statements],
                    citations=citations,
                    removed_unsupported=removed,
                    notice="AI-drafted answer. Every statement cites the passages below; "
                    "statements without a valid citation were removed. Verify each "
                    "citation before relying on it.",
                )
            except AIError as exc:
                logger.info("ask fell back to retrieval-only (error_type=%s)", type(exc).__name__)
        if not sources:
            answer = [
                AskStatement(
                    text="The processed evidence of this case contains no passage matching this "
                    "question. This does not mean the answer is 'no'; the evidence may not "
                    "cover it or may use different words.",
                    citations=[],
                    support="unknown",
                )
            ]
        else:
            answer = [
                AskStatement(
                    text=f"{c.evidence_name} states: “{c.excerpt}”",
                    citations=[c.ref],
                    support="supported",
                )
                for c in citations[:4]
            ]
        reason = (
            "AI is not enabled for this case"
            if client is None
            else "the AI provider did not return a usable answer"
        )
        return AskOut(
            question=question,
            method="retrieval only (no AI)",
            answer=answer,
            citations=citations,
            removed_unsupported=0,
            notice=f"Retrieval-only answer ({reason}): the most relevant source passages, "
            "quoted verbatim. EvidenceX did not interpret them.",
        )

    # --- reports ------------------------------------------------------------------

    def _report_out(self, r: Report) -> ReportOut:
        snap = r.snapshot or {}
        return ReportOut(
            id=r.id,
            kind=r.kind,
            format=r.format,
            title=r.title,
            version=r.version,
            content_sha256=r.content_sha256,
            byte_size=r.byte_size,
            page_count=r.page_count,
            created_by=r.created_by,
            created_at=r.created_at,
            summary=snap.get("summary", {}),
        )

    def list_reports(self, case_id: uuid.UUID) -> ReportList:
        self._case(case_id)
        rows = list(
            self._db.scalars(
                select(Report).where(Report.case_id == case_id).order_by(Report.created_at.desc())
            )
        )
        return ReportList(items=[self._report_out(r) for r in rows], total=len(rows))

    def get_report(self, case_id: uuid.UUID, report_id: uuid.UUID) -> Report:
        r = self._db.scalar(select(Report).where(Report.id == report_id, Report.case_id == case_id))
        if r is None:
            raise NotFoundError("report not found")
        return r

    def _next_version(self, case_id: uuid.UUID, kind: str) -> int:
        n = self._db.scalar(
            select(func.max(Report.version)).where(Report.case_id == case_id, Report.kind == kind)
        )
        return int(n or 0) + 1

    def create_report(self, case_id: uuid.UUID, req: ReportCreate) -> ReportOut:
        case = self._case(case_id)
        version = self._next_version(case_id, req.kind)
        actor = current_actor()
        if req.kind == "investigation":
            from app.modules.analysis import reports

            snap = reports.build_snapshot(self._db, case_id)
            ai_summary, ai_note = None, None
            if req.include_ai_summary:
                ai_summary, ai_note = self._ai_brief(case, snap)
            html_text = reports.render_html(snap, version=version, ai_summary=ai_summary)
            content, pages = reports.html_to_pdf(
                html_text,
                title=f"Investigation report — {case.title}",
                header=f"EvidenceX · {case.title} · investigation report v{version}",
            )
            index = reports.snapshot_index(snap)
            summary = {
                "evidence": len(snap["evidence"]),
                "claims": len(snap["claims"]),
                "events": len(snap["events"]),
                "contradictions": len(snap["contradictions"]),
                "confirmed_contradictions": sum(
                    1 for c in snap["contradictions"] if c["review_status"] == "confirmed"
                ),
                "ai_summary": bool(ai_summary),
                "ai_summary_note": ai_note,
                "run_method": (snap.get("run") or {}).get("method"),
            }
            title = f"Investigation report — {case.title}"
        else:
            from app.modules.analysis import graph_export
            from app.modules.analysis.service import AnalysisService

            graph = AnalysisService(self._db).graph(
                case_id,
                include_claims=True,
                entity_type=req.entity_type,
                evidence_id=req.evidence_id,
                contradictions_only=False,
                limit=400,
            )
            scope = "filtered view" if (req.entity_type or req.evidence_id) else "whole case"
            content, pages, stats = graph_export.graph_pdf(
                graph, {"id": str(case.id), "title": case.title}, scope=scope
            )
            index = {"nodes": [n.id for n in graph.nodes][:2000], "truncated": graph.truncated}
            summary = {**stats, "scope": scope}
            title = f"Knowledge graph — {case.title}"
        row = Report(
            case_id=case_id,
            kind=req.kind,
            format="pdf",
            title=title,
            version=version,
            content=content,
            content_sha256=hashlib.sha256(content).hexdigest(),
            byte_size=len(content),
            page_count=pages,
            snapshot={"index": index, "summary": summary},
            analysis_run_id=uuid.UUID(index["run_id"]) if index.get("run_id") else None,
            created_by=actor.label if actor else None,
        )
        self._db.add(row)
        self._db.flush()
        record_action(
            self._db,
            case_id,
            "report",
            row.id,
            "generate",
            to_status=req.kind,
            payload={"version": version, "sha256": row.content_sha256, "pages": pages},
        )
        self._db.commit()
        return self._report_out(row)

    def _ai_brief(self, case: Case, snap: dict[str, Any]) -> tuple[list | None, str]:
        client = _ai_client(self._settings, case)
        if client is None:
            return None, "AI summary not included: AI is not enabled or allowed for this case."
        findings = []
        for c in snap["contradictions"]:
            if c["review_status"] in ("confirmed", "resolved", "unresolved"):
                findings.append(
                    {
                        "ref": f"F{len(findings) + 1}",
                        "type": "potential inconsistency",
                        "status": c["review_status"],
                        "why": c["explanation"]["why"],
                    }
                )
        for e in snap["events"]:
            if e["status"] == "confirmed":
                findings.append(
                    {
                        "ref": f"F{len(findings) + 1}",
                        "type": "confirmed event",
                        "title": e["title"],
                        "accounts": [m["claim"]["quote"] for m in e["members"]][:6],
                    }
                )
        for c in snap["claims"]:
            if c["review_status"] == "verified" and len(findings) < 40:
                findings.append(
                    {"ref": f"F{len(findings) + 1}", "type": "verified claim", "quote": c["quote"]}
                )
        if not findings:
            return None, "AI summary not included: there are no reviewed findings yet."
        from app.ai.gemini_client import AIError
        from app.ai.qa import brief

        try:
            statements, removed = brief(client, findings)
        except AIError as exc:
            return None, f"AI summary not included: the provider failed ({type(exc).__name__})."
        return statements, f"{removed} uncited or disallowed sentence(s) removed."

    # --- graph exports ----------------------------------------------------------

    def graph_export(
        self,
        case_id: uuid.UUID,
        fmt: str,
        *,
        entity_type: str | None,
        evidence_id: uuid.UUID | None,
        include_claims: bool,
    ) -> tuple[bytes, str, str]:
        from app.modules.analysis import graph_export
        from app.modules.analysis.service import AnalysisService

        case = self._case(case_id)
        graph = AnalysisService(self._db).graph(
            case_id,
            include_claims=include_claims,
            entity_type=entity_type,
            evidence_id=evidence_id,
            contradictions_only=False,
            limit=1000,
        )
        if fmt == "json":
            return (
                graph_export.to_json(graph, {"id": str(case.id), "title": case.title}),
                "application/json",
                "json",
            )
        if fmt == "graphml":
            return graph_export.to_graphml(graph), "application/graphml+xml", "graphml"
        raise BadRequestError("format must be json or graphml")
