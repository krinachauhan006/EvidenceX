"""HTTP endpoints for cases. Thin layer that delegates to the service."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.cases.schemas import (
    CaseCreate,
    CaseList,
    CaseOut,
    CaseStatus,
    CaseUpdate,
)
from app.modules.cases.service import DEFAULT_LIMIT, MAX_LIMIT, CaseService

router = APIRouter(prefix="/api/cases", tags=["cases"])


def get_service(db: Session = Depends(get_db)) -> CaseService:
    return CaseService(db)


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
def create_case(payload: CaseCreate, service: CaseService = Depends(get_service)) -> CaseOut:
    case = service.create(payload)
    return CaseOut.model_validate(case)


@router.get("", response_model=CaseList)
def list_cases(
    service: CaseService = Depends(get_service),
    status_filter: CaseStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> CaseList:
    items, total, used_limit, used_offset = service.list(
        status=status_filter, limit=limit, offset=offset
    )
    return CaseList(
        items=[CaseOut.model_validate(c) for c in items],
        total=total,
        limit=used_limit,
        offset=used_offset,
    )


@router.get("/{case_id}", response_model=CaseOut)
def get_case(case_id: uuid.UUID, service: CaseService = Depends(get_service)) -> CaseOut:
    return CaseOut.model_validate(service.get(case_id))


@router.patch("/{case_id}", response_model=CaseOut)
def update_case(
    case_id: uuid.UUID,
    payload: CaseUpdate,
    service: CaseService = Depends(get_service),
) -> CaseOut:
    return CaseOut.model_validate(service.update(case_id, payload))


@router.post("/{case_id}/archive", response_model=CaseOut)
def archive_case(case_id: uuid.UUID, service: CaseService = Depends(get_service)) -> CaseOut:
    return CaseOut.model_validate(service.archive(case_id))


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_case(case_id: uuid.UUID, service: CaseService = Depends(get_service)) -> Response:
    service.delete(case_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
