"""Data access for cases. No business logic here."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.cases.models import Case
from app.modules.cases.schemas import CaseStatus


class CaseRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, *, title: str, description: str | None) -> Case:
        case = Case(title=title, description=description, status="open")
        self._db.add(case)
        self._db.commit()
        self._db.refresh(case)
        return case

    def get(self, case_id: uuid.UUID) -> Case | None:
        return self._db.get(Case, case_id)

    def list(
        self,
        *,
        status: CaseStatus | None,
        limit: int,
        offset: int,
        member_user_id: uuid.UUID | None = None,
    ) -> tuple[list[Case], int]:
        """Return (items, total). Archived cases are excluded unless explicitly
        requested via ``status``. With ``member_user_id`` only that user's cases."""
        filters = []
        if member_user_id is not None:
            from app.modules.auth.models import CaseMember

            filters.append(
                Case.id.in_(select(CaseMember.case_id).where(CaseMember.user_id == member_user_id))
            )
        if status is not None:
            filters.append(Case.status == status)
        else:
            # Default view excludes archived cases (Requirement 5.2).
            filters.append(Case.status != "archived")

        total = self._db.scalar(select(func.count()).select_from(Case).where(*filters)) or 0
        rows = self._db.scalars(
            select(Case)
            .where(*filters)
            .order_by(Case.updated_at.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return list(rows), int(total)

    def update(self, case: Case) -> Case:
        self._db.add(case)
        self._db.commit()
        self._db.refresh(case)
        return case

    def delete(self, case: Case) -> None:
        self._db.delete(case)
        self._db.commit()
