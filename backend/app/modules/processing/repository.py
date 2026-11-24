"""Data access for processing: claims, run history and segments.

Every read is scoped by ``case_id`` (and ``evidence_id`` where relevant) so one
case can never see another case's extraction data.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.db_types import utcnow
from app.modules.evidence.models import Evidence
from app.modules.processing.extractors.base import ExtractionResult
from app.modules.processing.locators import locator_to_json, promoted_columns
from app.modules.processing.models import Extraction, ExtractionSegment

SEGMENT_INSERT_BATCH = 1000


def _batches(items: Sequence, size: int) -> Iterator[Sequence]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class ProcessingRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    # --- evidence lookups -------------------------------------------------------

    def get_evidence(self, case_id: uuid.UUID, evidence_id: uuid.UUID) -> Evidence | None:
        # populate_existing: always reflect the database, not a cached instance.
        return self._db.scalar(
            select(Evidence)
            .where(Evidence.id == evidence_id, Evidence.case_id == case_id)
            .execution_options(populate_existing=True)
        )

    def list_evidence(self, case_id: uuid.UUID, status: str | None = None) -> list[Evidence]:
        stmt = select(Evidence).where(Evidence.case_id == case_id)
        if status is not None:
            stmt = stmt.where(Evidence.processing_status == status)
        stmt = stmt.order_by(Evidence.created_at.asc(), Evidence.id.asc())
        return list(self._db.scalars(stmt.execution_options(populate_existing=True)).all())

    # --- claim ------------------------------------------------------------------

    def claim(
        self,
        case_id: uuid.UUID,
        evidence_id: uuid.UUID,
        *,
        force: bool,
        now: datetime,
        stale_cutoff: datetime,
    ) -> bool:
        """Atomically move an eligible item to ``processing``.

        One conditional UPDATE decides who wins, so two concurrent requests can
        never both process the same item. Returns True only for the winner.
        """
        eligible = [Evidence.processing_status.in_(("pending", "failed"))]
        if force:
            eligible.append(Evidence.processing_status == "completed")
        eligible.append(
            and_(
                Evidence.processing_status == "processing",
                Evidence.processing_started_at < stale_cutoff,
            )
        )
        result = self._db.execute(
            update(Evidence)
            .where(Evidence.id == evidence_id, Evidence.case_id == case_id, or_(*eligible))
            .values(
                processing_status="processing",
                processing_started_at=now,
                processing_completed_at=None,
                processing_error=None,
                processing_error_code=None,
                processing_attempts=Evidence.processing_attempts + 1,
            )
            .execution_options(synchronize_session=False)
        )
        self._db.commit()
        return bool(result.rowcount)

    # --- writing results --------------------------------------------------------

    def record_success(
        self,
        evidence: Evidence,
        *,
        run_number: int,
        started_at: datetime,
        result: ExtractionResult,
        source_sha256: str,
        duration_ms: int,
    ) -> Extraction:
        """Persist a completed run in ONE transaction.

        The previous current run is demoted, the new run and all its segments are
        inserted, and the evidence is marked completed. If anything fails, nothing
        is committed and the previous current run stays current.
        """
        now = utcnow()
        self._db.execute(
            update(Extraction)
            .where(Extraction.evidence_id == evidence.id, Extraction.is_current.is_(True))
            .values(is_current=False)
            .execution_options(synchronize_session="fetch")
        )
        extraction = Extraction(
            evidence_id=evidence.id,
            case_id=evidence.case_id,
            run_number=run_number,
            run_status="completed",
            is_current=True,
            extractor=result.extractor,
            extractor_version=result.extractor_version,
            source_sha256=source_sha256,
            outcome=result.outcome,
            doc_metadata=result.metadata,
            warnings=[w.to_dict() for w in result.warnings],
            segment_count=len(result.segments),
            duration_ms=duration_ms,
            started_at=started_at,
        )
        self._db.add(extraction)
        self._db.flush()

        seq = 0
        for batch in _batches(result.segments, SEGMENT_INSERT_BATCH):
            rows = []
            for draft in batch:
                page, t_start, t_end = promoted_columns(draft.locator)
                rows.append(
                    ExtractionSegment(
                        extraction_id=extraction.id,
                        evidence_id=evidence.id,
                        case_id=evidence.case_id,
                        seq=seq,
                        segment_type=draft.segment_type,
                        text=draft.text,
                        data=draft.data,
                        locator=locator_to_json(draft.locator),
                        page=page,
                        t_start=t_start,
                        t_end=t_end,
                        engine_confidence=draft.engine_confidence,
                        language=draft.language,
                    )
                )
                seq += 1
            self._db.add_all(rows)
            self._db.flush()

        evidence.processing_status = "completed"
        evidence.processing_completed_at = now
        evidence.processing_error = None
        evidence.processing_error_code = None
        self._db.commit()
        return extraction

    def record_failure(
        self,
        evidence: Evidence,
        *,
        run_number: int,
        started_at: datetime,
        extractor_name: str,
        extractor_version: str,
        source_sha256: str,
        error_code: str,
        error_message: str,
        duration_ms: int,
    ) -> Extraction:
        """Record a failed run and mark the evidence failed. A failed run is never
        current, so an earlier successful run stays current and readable."""
        now = utcnow()
        extraction = Extraction(
            evidence_id=evidence.id,
            case_id=evidence.case_id,
            run_number=run_number,
            run_status="failed",
            is_current=False,
            extractor=extractor_name,
            extractor_version=extractor_version,
            source_sha256=source_sha256,
            outcome=None,
            error_code=error_code,
            error_message=error_message,
            doc_metadata={},
            warnings=[],
            segment_count=0,
            duration_ms=duration_ms,
            started_at=started_at,
        )
        self._db.add(extraction)
        evidence.processing_status = "failed"
        evidence.processing_completed_at = now
        evidence.processing_error = error_message
        evidence.processing_error_code = error_code
        self._db.commit()
        return extraction

    # --- reads ------------------------------------------------------------------

    def get_current_extraction(
        self, case_id: uuid.UUID, evidence_id: uuid.UUID
    ) -> Extraction | None:
        return self._db.scalar(
            select(Extraction)
            .where(
                Extraction.case_id == case_id,
                Extraction.evidence_id == evidence_id,
                Extraction.is_current.is_(True),
            )
            .execution_options(populate_existing=True)
        )

    def get_extraction(
        self, case_id: uuid.UUID, evidence_id: uuid.UUID, extraction_id: uuid.UUID
    ) -> Extraction | None:
        return self._db.scalar(
            select(Extraction)
            .where(
                Extraction.id == extraction_id,
                Extraction.case_id == case_id,
                Extraction.evidence_id == evidence_id,
            )
            .execution_options(populate_existing=True)
        )

    def list_extractions(
        self, case_id: uuid.UUID, evidence_id: uuid.UUID
    ) -> list[Extraction]:
        return list(
            self._db.scalars(
                select(Extraction)
                .where(Extraction.case_id == case_id, Extraction.evidence_id == evidence_id)
                .order_by(Extraction.run_number.desc())
                .execution_options(populate_existing=True)
            ).all()
        )

    def list_segments(
        self,
        case_id: uuid.UUID,
        evidence_id: uuid.UUID,
        extraction_id: uuid.UUID,
        *,
        page: int | None,
        segment_type: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ExtractionSegment], int]:
        filters = [
            ExtractionSegment.case_id == case_id,
            ExtractionSegment.evidence_id == evidence_id,
            ExtractionSegment.extraction_id == extraction_id,
        ]
        if page is not None:
            filters.append(ExtractionSegment.page == page)
        if segment_type is not None:
            filters.append(ExtractionSegment.segment_type == segment_type)
        total = (
            self._db.scalar(select(func.count()).select_from(ExtractionSegment).where(*filters))
            or 0
        )
        rows = self._db.scalars(
            select(ExtractionSegment)
            .where(*filters)
            .order_by(ExtractionSegment.seq.asc())
            .limit(limit)
            .offset(offset)
        ).all()
        return list(rows), int(total)

    def latest_segment_reviews(self, segment_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Any]:
        """segment id -> newest human correction (``SegmentReview``), if any."""
        from app.modules.analysis.models import SegmentReview

        if not segment_ids:
            return {}
        rows = self._db.scalars(
            select(SegmentReview)
            .where(SegmentReview.segment_id.in_(list(segment_ids)))
            .order_by(SegmentReview.created_at.asc(), SegmentReview.id.asc())
        ).all()
        return {r.segment_id: r for r in rows}  # later rows overwrite earlier ones

    def case_overview(
        self, case_id: uuid.UUID
    ) -> list[tuple[Evidence, Extraction | None]]:
        """Every evidence item in the case with its current run (if any)."""
        stmt = (
            select(Evidence, Extraction)
            .outerjoin(
                Extraction,
                and_(Extraction.evidence_id == Evidence.id, Extraction.is_current.is_(True)),
            )
            .where(Evidence.case_id == case_id)
            .order_by(Evidence.created_at.asc(), Evidence.id.asc())
            .execution_options(populate_existing=True)
        )
        return [(ev, ex) for ev, ex in self._db.execute(stmt).all()]
