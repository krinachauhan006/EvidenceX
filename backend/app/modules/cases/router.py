"""HTTP endpoints for cases. Thin layer that delegates to the service.

Every route requires a signed-in user (``authorize``). Case-scoped routes also
require a membership with a sufficient role; listing returns only the caller's cases.
"""

from __future__ import annotations

import uuid
from collections import Counter

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.deps import authorize
from app.modules.auth.models import CaseMember
from app.modules.auth.service import AuthService
from app.modules.cases.schemas import (
    CaseCreate,
    CaseList,
    CaseOut,
    CaseStatus,
    CaseUpdate,
    ConsentUpdate,
)
from app.modules.cases.service import DEFAULT_LIMIT, MAX_LIMIT, CaseService

router = APIRouter(prefix="/api/cases", tags=["cases"], dependencies=[Depends(authorize)])
workspace_router = APIRouter(
    prefix="/api/workspace", tags=["cases"], dependencies=[Depends(authorize)]
)


def get_service(db: Session = Depends(get_db)) -> CaseService:
    return CaseService(db)


def _roles(db: Session, user_id: uuid.UUID) -> dict[uuid.UUID, str]:
    return dict(
        db.execute(
            select(CaseMember.case_id, CaseMember.role).where(CaseMember.user_id == user_id)
        ).all()
    )


def _out(case, role: str | None) -> CaseOut:  # noqa: ANN001
    out = CaseOut.model_validate(case)
    out.my_role = role
    return out


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
def create_case(
    payload: CaseCreate,
    request: Request,
    service: CaseService = Depends(get_service),
    db: Session = Depends(get_db),
) -> CaseOut:
    case = service.create(payload)
    AuthService(db).add_owner(case.id, request.state.user)
    return _out(case, "owner")


@router.get("", response_model=CaseList)
def list_cases(
    request: Request,
    service: CaseService = Depends(get_service),
    db: Session = Depends(get_db),
    status_filter: CaseStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> CaseList:
    user = request.state.user
    items, total, used_limit, used_offset = service.list(
        status=status_filter, limit=limit, offset=offset, member_user_id=user.id
    )
    roles = _roles(db, user.id)
    return CaseList(
        items=[_out(c, roles.get(c.id)) for c in items],
        total=total,
        limit=used_limit,
        offset=used_offset,
    )


@router.get("/{case_id}", response_model=CaseOut)
def get_case(
    case_id: uuid.UUID, request: Request, service: CaseService = Depends(get_service)
) -> CaseOut:
    return _out(service.get(case_id), getattr(request.state, "case_role", None))


@router.patch("/{case_id}", response_model=CaseOut)
def update_case(
    case_id: uuid.UUID,
    payload: CaseUpdate,
    request: Request,
    service: CaseService = Depends(get_service),
) -> CaseOut:
    return _out(service.update(case_id, payload), getattr(request.state, "case_role", None))


@router.post("/{case_id}/consent", response_model=CaseOut)
def set_consent(
    case_id: uuid.UUID,
    payload: ConsentUpdate,
    request: Request,
    service: CaseService = Depends(get_service),
) -> CaseOut:
    case = service.set_ai_consent(case_id, payload.ai_processing_allowed)
    return _out(case, getattr(request.state, "case_role", None))


@router.post("/{case_id}/archive", response_model=CaseOut)
def archive_case(
    case_id: uuid.UUID, request: Request, service: CaseService = Depends(get_service)
) -> CaseOut:
    return _out(service.archive(case_id), getattr(request.state, "case_role", None))


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_case(case_id: uuid.UUID, service: CaseService = Depends(get_service)) -> Response:
    service.delete(case_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@workspace_router.get("/summary")
def workspace_summary(request: Request, db: Session = Depends(get_db)) -> dict:
    """Totals across the caller's cases, computed from stored records only."""
    from app.modules.analysis.models import Claim, Event, PotentialContradiction
    from app.modules.cases.models import Case
    from app.modules.evidence.models import Evidence

    user = request.state.user
    case_ids = select(CaseMember.case_id).where(CaseMember.user_id == user.id)
    cases = list(db.scalars(select(Case).where(Case.id.in_(case_ids))))
    ev_status = Counter(
        dict(
            db.execute(
                select(Evidence.processing_status, func.count())
                .where(Evidence.case_id.in_(case_ids))
                .group_by(Evidence.processing_status)
            ).all()
        )
    )
    ev_types = dict(
        db.execute(
            select(Evidence.evidence_type, func.count())
            .where(Evidence.case_id.in_(case_ids))
            .group_by(Evidence.evidence_type)
        ).all()
    )

    def count(model, *where) -> int:  # noqa: ANN001
        return int(
            db.scalar(
                select(func.count()).select_from(model).where(model.case_id.in_(case_ids), *where)
            )
            or 0
        )

    open_claims = count(
        Claim,
        Claim.review_status.in_(("unreviewed", "needs_verification")),
        Claim.superseded_by_run_id.is_(None),
    )
    open_conflicts = count(
        PotentialContradiction,
        PotentialContradiction.review_status.in_(("unreviewed", "unresolved")),
    )
    proposed_events = count(Event, Event.status == "proposed")
    recent = sorted(cases, key=lambda c: c.updated_at, reverse=True)[:6]
    active = list(
        db.execute(
            select(Evidence.case_id, Evidence.original_filename, Evidence.processing_status)
            .where(
                Evidence.case_id.in_(case_ids),
                Evidence.processing_status.in_(("pending", "processing", "failed")),
            )
            .limit(20)
        ).all()
    )
    titles = {c.id: c.title for c in cases}
    return {
        "cases": {
            "total": len(cases),
            "open": sum(1 for c in cases if c.status == "open"),
            "archived": sum(1 for c in cases if c.status == "archived"),
        },
        "evidence": {
            "total": sum(ev_status.values()),
            "by_status": dict(ev_status),
            "by_type": ev_types,
        },
        "review": {
            "open_claims": open_claims,
            "open_contradictions": open_conflicts,
            "proposed_events": proposed_events,
        },
        "recent_cases": [
            {
                "id": str(c.id),
                "title": c.title,
                "status": c.status,
                "updated_at": c.updated_at.isoformat(),
            }
            for c in recent
        ],
        "processing_activity": [
            {"case_id": str(cid), "case_title": titles.get(cid), "file": name, "status": st}
            for cid, name, st in active
        ],
    }
