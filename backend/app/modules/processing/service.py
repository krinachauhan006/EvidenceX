"""Request-side processing logic: deciding what to queue, and reading results.

Nothing here extracts anything. Extraction runs later in ``ProcessingRunner``,
which claims each item atomically. The decisions made here are advisory: the
claim in the runner is the real guard against double processing.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db_types import as_utc, utcnow
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.modules.cases.repository import CaseRepository
from app.modules.evidence.models import Evidence
from app.modules.processing.audio_models import available_model_names, list_local_models
from app.modules.processing.registry import ExtractorRegistry
from app.modules.processing.repository import ProcessingRepository
from app.modules.processing.schemas import (
    AudioModelList,
    AudioModelOut,
    CaseProcessingSummary,
    ExtractionList,
    ExtractionOut,
    ProcessAccepted,
    ProcessingItemOut,
    ProcessingStatusOut,
    SegmentList,
    SegmentOut,
    SkippedItem,
    SkipReason,
    StatusCounts,
)

DEFAULT_SEGMENT_LIMIT = 100
MAX_SEGMENT_LIMIT = 500


class ProcessingService:
    def __init__(
        self,
        db: Session,
        registry: ExtractorRegistry,
        settings: Settings | None = None,
    ) -> None:
        self._repo = ProcessingRepository(db)
        self._cases = CaseRepository(db)
        self._registry = registry
        self._settings = settings or get_settings()

    # --- helpers ----------------------------------------------------------------

    def _require_case(self, case_id: uuid.UUID) -> None:
        if self._cases.get(case_id) is None:
            raise NotFoundError("case not found")

    def _evidence(self, case_id: uuid.UUID, evidence_id: uuid.UUID) -> Evidence:
        evidence = self._repo.get_evidence(case_id, evidence_id)
        if evidence is None:
            raise NotFoundError("evidence not found")
        return evidence

    def _skip_reason(self, evidence: Evidence, *, force: bool) -> SkipReason | None:
        """Why this item should not be queued, or None if it can be."""
        if not self._registry.supports(evidence.mime_type):
            return "no_extractor"
        if evidence.processing_status == "completed" and not force:
            return "already_completed"
        if evidence.processing_status == "processing":
            started = evidence.processing_started_at
            cutoff = utcnow() - timedelta(minutes=self._settings.processing_stale_minutes)
            if started is None or as_utc(started) >= cutoff:
                return "already_processing"
            if self.is_external(evidence):
                # A stale item of an external type belongs to the worker, which
                # reclaims it; this server must not claim (and then fail) it.
                return "already_processing"
        if self.is_external(evidence):
            # Never queued here, so never claimed or marked failed by this server. The
            # item keeps its status ("pending", or "failed" from before the setting)
            # and the external processing worker picks it up.
            return "external_worker"
        return None

    def is_external(self, evidence: Evidence) -> bool:
        """Whether this server leaves the item's file type to the external worker."""
        return evidence.mime_type in self._settings.external_worker_mimes

    def _decide(self, evidences: list[Evidence], *, force: bool) -> ProcessAccepted:
        queued: list[uuid.UUID] = []
        skipped: list[SkippedItem] = []
        for evidence in evidences:
            reason = self._skip_reason(evidence, force=force)
            if reason is None:
                queued.append(evidence.id)
            else:
                skipped.append(SkippedItem(evidence_id=evidence.id, reason=reason))
        return ProcessAccepted(queued=queued, skipped=skipped)

    # --- enqueue ----------------------------------------------------------------

    def enqueue_one(
        self,
        case_id: uuid.UUID,
        evidence_id: uuid.UUID,
        *,
        force: bool,
        audio_model: str | None = None,
        ocr_languages: str | None = None,
    ) -> tuple[ProcessAccepted, dict[str, Any]]:
        """Decision plus the engine option overrides the run must use."""
        evidence = self._evidence(case_id, evidence_id)
        overrides = self.check_audio_model(evidence, audio_model)
        overrides.update(self.check_ocr_languages(evidence, ocr_languages))
        return self._decide([evidence], force=force), overrides

    def check_ocr_languages(self, evidence: Evidence, value: str | None) -> dict[str, Any]:
        if value is None:
            return {}
        if evidence.evidence_type not in ("image", "document", "video"):
            raise BadRequestError("OCR languages apply to images, PDFs and video only")
        from app.modules.processing.extractors.ocr_languages import (
            installed_languages,
            validate_languages,
        )

        try:
            langs, missing = validate_languages(
                value, installed_languages(self._settings.tesseract_cmd)
            )
        except ValueError as exc:
            raise BadRequestError(str(exc)) from None
        if missing:
            raise BadRequestError(
                f"OCR language pack(s) not installed: {', '.join(missing)}. They are never "
                "downloaded automatically; see GET /api/ocr/languages for install help"
            )
        return {"tesseract_langs": langs}

    def enqueue_pending(self, case_id: uuid.UUID) -> ProcessAccepted:
        self._require_case(case_id)
        return self._decide(self._repo.list_evidence(case_id, status="pending"), force=False)

    def enqueue_retry(self, case_id: uuid.UUID, evidence_id: uuid.UUID) -> ProcessAccepted:
        evidence = self._evidence(case_id, evidence_id)
        if evidence.processing_status != "failed":
            raise ConflictError("only failed evidence can be retried")
        return self._decide([evidence], force=False)

    # --- reads ------------------------------------------------------------------

    def status(self, case_id: uuid.UUID, evidence_id: uuid.UUID) -> ProcessingStatusOut:
        evidence = self._evidence(case_id, evidence_id)
        current = self._repo.get_current_extraction(case_id, evidence_id)
        return ProcessingStatusOut(
            evidence_id=evidence.id,
            status=evidence.processing_status,  # type: ignore[arg-type]
            error=evidence.processing_error,
            error_code=evidence.processing_error_code,
            attempts=evidence.processing_attempts,
            started_at=evidence.processing_started_at,
            completed_at=evidence.processing_completed_at,
            has_current_extraction=current is not None,
            current_extraction=ExtractionOut.model_validate(current) if current else None,
        )

    def current_extraction(self, case_id: uuid.UUID, evidence_id: uuid.UUID) -> ExtractionOut:
        self._evidence(case_id, evidence_id)
        current = self._repo.get_current_extraction(case_id, evidence_id)
        if current is None:
            raise NotFoundError("no extraction available yet")
        return ExtractionOut.model_validate(current)

    def list_extractions(self, case_id: uuid.UUID, evidence_id: uuid.UUID) -> ExtractionList:
        self._evidence(case_id, evidence_id)
        runs = self._repo.list_extractions(case_id, evidence_id)
        return ExtractionList(
            items=[ExtractionOut.model_validate(r) for r in runs], total=len(runs)
        )

    def get_extraction(
        self, case_id: uuid.UUID, evidence_id: uuid.UUID, extraction_id: uuid.UUID
    ) -> ExtractionOut:
        self._evidence(case_id, evidence_id)
        run = self._repo.get_extraction(case_id, evidence_id, extraction_id)
        if run is None:
            raise NotFoundError("extraction not found")
        return ExtractionOut.model_validate(run)

    def segments(
        self,
        case_id: uuid.UUID,
        evidence_id: uuid.UUID,
        *,
        extraction_id: uuid.UUID | None,
        page: int | None,
        segment_type: str | None,
        limit: int,
        offset: int,
    ) -> SegmentList:
        self._evidence(case_id, evidence_id)
        if extraction_id is None:
            run = self._repo.get_current_extraction(case_id, evidence_id)
            if run is None:
                raise NotFoundError("no extraction available yet")
        else:
            run = self._repo.get_extraction(case_id, evidence_id, extraction_id)
            if run is None:
                raise NotFoundError("extraction not found")
        limit = max(1, min(limit, MAX_SEGMENT_LIMIT))
        offset = max(0, offset)
        rows, total = self._repo.list_segments(
            case_id,
            evidence_id,
            run.id,
            page=page,
            segment_type=segment_type,
            limit=limit,
            offset=offset,
        )
        reviews = self._repo.latest_segment_reviews([r.id for r in rows])
        items = []
        for row in rows:
            item = SegmentOut.model_validate(row)
            review = reviews.get(row.id)
            if review is not None:
                item.review_status = "reviewed"
                item.reviewed_text = review.corrected_text
                item.reviewed_by = review.reviewer
                item.reviewed_at = review.created_at
            items.append(item)
        return SegmentList(items=items, total=total, limit=limit, offset=offset)

    # --- speech models ----------------------------------------------------------

    def audio_models(self) -> AudioModelList:
        default = self._settings.whisper_model_size
        found = list_local_models(self._settings.whisper_model_dir)
        names = {m.name for m in found}
        items = [
            AudioModelOut(
                name=m.name,
                repo=m.repo,
                available=m.available,
                size_bytes=m.size_bytes,
                problem=m.problem,
                is_default=m.name == default,
            )
            for m in found
        ]
        if default not in names:
            items.insert(
                0,
                AudioModelOut(
                    name=default,
                    repo="",
                    available=False,
                    size_bytes=None,
                    problem="the configured default model is not on disk",
                    is_default=True,
                ),
            )
        return AudioModelList(
            default=default,
            default_available=any(i.available and i.is_default for i in items),
            items=items,
        )

    def check_audio_model(self, evidence: Evidence, model: str | None) -> dict[str, Any]:
        """Engine option overrides for one run. Raises when the model cannot be used."""
        if model is None:
            return {}
        if evidence.evidence_type not in ("audio", "video"):
            raise BadRequestError("a speech model can only be chosen for audio or video evidence")
        if model not in available_model_names(self._settings.whisper_model_dir):
            raise BadRequestError(
                f"the speech model '{model}' is not available locally; it is never "
                "downloaded or substituted automatically"
            )
        return {"whisper_model_size": model}

    def case_summary(self, case_id: uuid.UUID) -> CaseProcessingSummary:
        self._require_case(case_id)
        counts = StatusCounts()
        items: list[ProcessingItemOut] = []
        for evidence, current in self._repo.case_overview(case_id):
            counts.total += 1
            status_name = evidence.processing_status
            setattr(counts, status_name, getattr(counts, status_name) + 1)
            items.append(
                ProcessingItemOut(
                    evidence_id=evidence.id,
                    original_filename=evidence.original_filename,
                    evidence_type=evidence.evidence_type,  # type: ignore[arg-type]
                    status=evidence.processing_status,  # type: ignore[arg-type]
                    error_code=evidence.processing_error_code,
                    attempts=evidence.processing_attempts,
                    outcome=current.outcome if current else None,  # type: ignore[arg-type]
                    segment_count=current.segment_count if current else 0,
                    run_number=current.run_number if current else None,
                    extractor_available=self._registry.supports(evidence.mime_type),
                    external_worker=self.is_external(evidence),
                )
            )
        return CaseProcessingSummary(counts=counts, items=items)
