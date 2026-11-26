"""Phase 2 endpoints: events, timeline, search, Q&A, reports, graph exports, audit
verification and AI status. Mounted with the ``authorize`` dependency."""

from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.modules.analysis.audit import verify_chain
from app.modules.analysis.event_service import EventService
from app.modules.analysis.phase2_service import Phase2Service
from app.modules.analysis.schemas_phase2 import (
    AskOut,
    AskRequest,
    EventCreate,
    EventDetail,
    EventList,
    EventReviewRequest,
    ReportCreate,
    ReportList,
    ReportOut,
    SearchOut,
    TimelineOut,
)
from app.modules.cases.repository import CaseRepository

router = APIRouter(prefix="/api/cases/{case_id}", tags=["phase2"])
ai_router = APIRouter(prefix="/api/ai", tags=["phase2"])


def _events(db: Session = Depends(get_db)) -> EventService:
    return EventService(db)


def _p2(db: Session = Depends(get_db)) -> Phase2Service:
    return Phase2Service(db)


def _require_case(db: Session, case_id: uuid.UUID) -> None:
    if CaseRepository(db).get(case_id) is None:
        raise NotFoundError("case not found")


def _attachment(data: bytes, media: str, filename: str, inline: bool = False) -> Response:
    ascii_name = filename.encode("ascii", "ignore").decode() or "export"
    disp = "inline" if inline else "attachment"
    return Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition": f'{disp}; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(filename)}",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, no-store",
        },
    )


# --- events -------------------------------------------------------------------------


@router.get("/events", response_model=EventList)
def list_events(
    case_id: uuid.UUID,
    service: EventService = Depends(_events),
    db: Session = Depends(get_db),
    status_filter: str | None = Query(default=None, alias="status", max_length=16),
    event_type: str | None = Query(default=None, max_length=48),
) -> EventList:
    _require_case(db, case_id)
    return service.list_events(case_id, status=status_filter, event_type=event_type)


@router.post("/events", response_model=EventDetail, status_code=status.HTTP_201_CREATED)
def create_event(
    case_id: uuid.UUID,
    payload: EventCreate,
    service: EventService = Depends(_events),
    db: Session = Depends(get_db),
) -> EventDetail:
    _require_case(db, case_id)
    return service.create_event(case_id, payload)


@router.post("/events/propose")
def propose_events(
    case_id: uuid.UUID, service: EventService = Depends(_events), db: Session = Depends(get_db)
) -> dict:
    """Re-run the rule-based proposal step (e.g. after reviewing claims)."""
    _require_case(db, case_id)
    made = service.propose(case_id)
    db.commit()
    return {"created": made}


@router.get("/events/{event_id}", response_model=EventDetail)
def get_event(
    case_id: uuid.UUID, event_id: uuid.UUID, service: EventService = Depends(_events)
) -> EventDetail:
    return service.get_event(case_id, event_id)


@router.post("/events/{event_id}/review", response_model=EventDetail)
def review_event(
    case_id: uuid.UUID,
    event_id: uuid.UUID,
    payload: EventReviewRequest,
    service: EventService = Depends(_events),
) -> EventDetail:
    return service.review(case_id, event_id, payload)


# --- timeline -----------------------------------------------------------------------


@router.get("/timeline", response_model=TimelineOut)
def timeline(
    case_id: uuid.UUID,
    service: EventService = Depends(_events),
    db: Session = Depends(get_db),
    evidence_id: uuid.UUID | None = Query(default=None),
    entity_id: uuid.UUID | None = Query(default=None),
    event_id: uuid.UUID | None = Query(default=None),
    review_status: str | None = Query(default=None, max_length=24),
    modality: str | None = Query(default=None, max_length=16),
    date_from: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> TimelineOut:
    _require_case(db, case_id)
    return service.timeline(
        case_id,
        evidence_id=evidence_id,
        entity_id=entity_id,
        event_id=event_id,
        review_status=review_status,
        date_from=date_from,
        date_to=date_to,
        modality=modality,
    )


# --- search and Q&A ------------------------------------------------------------------


@router.get("/search", response_model=SearchOut)
def search(
    case_id: uuid.UUID,
    service: Phase2Service = Depends(_p2),
    q: str = Query(min_length=1, max_length=300),
    kinds: str | None = Query(default=None, max_length=60, pattern=r"^[a-z,]+$"),
    evidence_id: uuid.UUID | None = Query(default=None),
    modality: str | None = Query(default=None, max_length=16),
    review_status: str | None = Query(default=None, max_length=24),
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    entity_id: uuid.UUID | None = Query(default=None),
    event_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
) -> SearchOut:
    kind_set = None
    if kinds:
        kind_set = {k for k in kinds.split(",") if k in ("segment", "claim", "entity", "event")}
    return service.search(
        case_id,
        q,
        kinds=kind_set,
        evidence_id=evidence_id,
        modality=modality,
        review_status=review_status,
        min_confidence=min_confidence,
        entity_id=entity_id,
        event_id=event_id,
        limit=limit,
    )


@router.post("/ask", response_model=AskOut)
def ask(case_id: uuid.UUID, payload: AskRequest, service: Phase2Service = Depends(_p2)) -> AskOut:
    return service.ask(case_id, payload.question)


# --- reports and exports ---------------------------------------------------------------


@router.post("/reports", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
def create_report(
    case_id: uuid.UUID, payload: ReportCreate, service: Phase2Service = Depends(_p2)
) -> ReportOut:
    return service.create_report(case_id, payload)


@router.get("/reports", response_model=ReportList)
def list_reports(case_id: uuid.UUID, service: Phase2Service = Depends(_p2)) -> ReportList:
    return service.list_reports(case_id)


@router.get("/reports/{report_id}", response_model=ReportOut)
def get_report(
    case_id: uuid.UUID, report_id: uuid.UUID, service: Phase2Service = Depends(_p2)
) -> ReportOut:
    return service._report_out(service.get_report(case_id, report_id))


@router.get("/reports/{report_id}/download")
def download_report(
    case_id: uuid.UUID,
    report_id: uuid.UUID,
    service: Phase2Service = Depends(_p2),
    inline: bool = Query(default=False),
) -> Response:
    r = service.get_report(case_id, report_id)
    name = f"evidencex-{r.kind}-report-v{r.version}.pdf"
    return _attachment(r.content, "application/pdf", name, inline=inline)


@router.get("/graph/export")
def export_graph(
    case_id: uuid.UUID,
    service: Phase2Service = Depends(_p2),
    format: str = Query(default="json", pattern=r"^(json|graphml)$"),  # noqa: A002
    entity_type: str | None = Query(default=None, max_length=32),
    evidence_id: uuid.UUID | None = Query(default=None),
    include_claims: bool = Query(default=True),
) -> Response:
    data, media, ext = service.graph_export(
        case_id,
        format,
        entity_type=entity_type,
        evidence_id=evidence_id,
        include_claims=include_claims,
    )
    return _attachment(data, media, f"evidencex-graph.{ext}")


# --- audit -------------------------------------------------------------------------------


@router.get("/reviews/verify")
def verify_audit(case_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    _require_case(db, case_id)
    return verify_chain(db, case_id)


# --- AI status (no evidence is sent) ---------------------------------------------------


@ai_router.get("/status")
def ai_status() -> dict:
    s = get_settings()
    return {
        "mode": s.claim_extractor,
        "provider": "Google Gemini API" if s.claim_extractor in ("gemini", "hybrid") else None,
        "model": s.gemini_model,
        "key_configured": bool(s.gemini_api_key),
        "available": bool(s.gemini_api_key) and s.claim_extractor in ("gemini", "hybrid"),
        "consent_required": True,
        "data_sent": (
            "Only extracted text segments (with their ids) of a case whose owner allowed AI "
            "processing, inside data delimiters. Never file bytes, file names, other cases, "
            "secrets or account data."
        ),
        "purposes": [
            "claim extraction",
            "grounded question answering",
            "AI-drafted report summary",
        ],
    }
