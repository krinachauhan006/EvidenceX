"""Data access for evidence. No business logic here.

All read/delete operations are scoped by case to enforce case-level isolation at
the query level.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.evidence.models import Evidence


class EvidenceRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, evidence: Evidence) -> Evidence:
        self._db.add(evidence)
        self._db.commit()
        self._db.refresh(evidence)
        return evidence

    def get_scoped(self, case_id: uuid.UUID, evidence_id: uuid.UUID) -> Evidence | None:
        """Return the evidence only if it belongs to the given case."""
        return self._db.scalar(
            select(Evidence).where(
                Evidence.id == evidence_id, Evidence.case_id == case_id
            )
        )

    def list_for_case(self, case_id: uuid.UUID) -> tuple[list[Evidence], int]:
        filters = (Evidence.case_id == case_id,)
        total = (
            self._db.scalar(select(func.count()).select_from(Evidence).where(*filters)) or 0
        )
        rows = self._db.scalars(
            select(Evidence)
            .where(*filters)
            .order_by(Evidence.created_at.desc())
        ).all()
        return list(rows), int(total)

    def delete(self, evidence: Evidence) -> None:
        self._db.delete(evidence)
        self._db.commit()

    def count_by_hash(self, sha256: str) -> int:
        """How many evidence rows (across all cases) reference this content hash."""
        return int(
            self._db.scalar(
                select(func.count()).select_from(Evidence).where(Evidence.sha256 == sha256)
            )
            or 0
        )

    def hashes_for_case(self, case_id: uuid.UUID) -> list[str]:
        return list(
            self._db.scalars(
                select(Evidence.sha256).where(Evidence.case_id == case_id)
            ).all()
        )
