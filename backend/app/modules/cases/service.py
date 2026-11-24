"""Business logic for cases."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.modules.cases.models import Case
from app.modules.cases.repository import CaseRepository
from app.modules.cases.schemas import CaseCreate, CaseStatus, CaseUpdate

# Keep the default/cap in one place so the router and tests agree.
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class CaseService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._repo = CaseRepository(db)

    def create(self, data: CaseCreate) -> Case:
        return self._repo.create(title=data.title, description=data.description)

    def get(self, case_id: uuid.UUID) -> Case:
        case = self._repo.get(case_id)
        if case is None:
            raise NotFoundError("case not found")
        return case

    def list(
        self,
        *,
        status: CaseStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Case], int, int, int]:
        limit = max(1, min(limit, MAX_LIMIT))
        offset = max(0, offset)
        items, total = self._repo.list(status=status, limit=limit, offset=offset)
        return items, total, limit, offset

    def update(self, case_id: uuid.UUID, data: CaseUpdate) -> Case:
        case = self.get(case_id)
        if data.title is not None:
            case.title = data.title
        if data.description is not None:
            case.description = data.description
        if data.status is not None:
            case.status = data.status
        return self._repo.update(case)

    def archive(self, case_id: uuid.UUID) -> Case:
        """Soft archive: hides the case from the default list but preserves all
        of its data. Reversible via update(status='open')."""
        case = self.get(case_id)
        case.status = "archived"
        return self._repo.update(case)

    def delete(self, case_id: uuid.UUID) -> None:
        """Hard delete the case. Owned records (e.g. evidence) are removed via FK
        ON DELETE CASCADE. Scoped to exactly this case id, so unrelated cases are
        never affected.

        Evidence blobs for this case are cleaned up best-effort before the cascade
        removes their rows. Blob cleanup must never block the case delete.
        """
        case = self.get(case_id)
        self._cleanup_evidence_blobs(case_id)
        self._repo.delete(case)

    def _cleanup_evidence_blobs(self, case_id: uuid.UUID) -> None:
        """Remove storage blobs owned solely by this case. Imported locally to
        avoid a module-level import cycle (evidence -> cases)."""
        from app.modules.evidence.service import EvidenceService

        try:
            EvidenceService(self._db).cleanup_case_blobs(case_id)
        except Exception:  # noqa: BLE001 - cleanup must not break case deletion
            pass
