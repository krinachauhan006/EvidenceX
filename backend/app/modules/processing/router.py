"""HTTP endpoints for evidence processing, nested under the owning case.

Process/retry endpoints only decide what to queue and return 202 immediately.
Extraction runs afterwards in a background task with its own database session.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.modules.processing.browser_schemas import (
    BrowserClaimIn,
    BrowserClaimOut,
    BrowserFailureIn,
    BrowserHeartbeatIn,
    BrowserResultIn,
)
from app.modules.processing.browser_service import BrowserProcessingService
from app.modules.processing.registry import ExtractorRegistry, get_registry
from app.modules.processing.runner import ProcessingRunner, build_default_runner
from app.modules.processing.schemas import (
    AudioModelList,
    CaseProcessingSummary,
    ExtractionList,
    ExtractionOut,
    ProcessAccepted,
    ProcessingStatusOut,
    ProcessRequest,
    SegmentList,
)
from app.modules.processing.service import (
    DEFAULT_SEGMENT_LIMIT,
    MAX_SEGMENT_LIMIT,
    ProcessingService,
)

router = APIRouter(prefix="/api/cases/{case_id}", tags=["processing"])
audio_router = APIRouter(prefix="/api/audio", tags=["processing"])


def get_processing_service(
    db: Session = Depends(get_db),
    registry: ExtractorRegistry = Depends(get_registry),
) -> ProcessingService:
    return ProcessingService(db, registry)


def get_runner() -> ProcessingRunner:
    return build_default_runner()


def get_browser_service(db: Session = Depends(get_db)) -> BrowserProcessingService:
    from app.storage.factory import build_storage

    settings = get_settings()
    return BrowserProcessingService(db, settings, build_storage(settings))


def _schedule(
    background_tasks: BackgroundTasks,
    runner: ProcessingRunner,
    case_id: uuid.UUID,
    accepted: ProcessAccepted,
    *,
    force: bool,
    options_override: dict[str, Any] | None = None,
) -> None:
    if accepted.queued:
        if options_override:
            background_tasks.add_task(
                runner.run_batch, case_id, list(accepted.queued), force, options_override
            )
        else:
            background_tasks.add_task(runner.run_batch, case_id, list(accepted.queued), force)


# --- queue work -----------------------------------------------------------------


@router.post(
    "/evidence/process-pending",
    response_model=ProcessAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def process_pending(
    case_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    service: ProcessingService = Depends(get_processing_service),
    runner: ProcessingRunner = Depends(get_runner),
) -> ProcessAccepted:
    accepted = service.enqueue_pending(case_id)
    _schedule(background_tasks, runner, case_id, accepted, force=False)
    return accepted


@router.post(
    "/evidence/{evidence_id}/process",
    response_model=ProcessAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def process_evidence(
    case_id: uuid.UUID,
    evidence_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    payload: ProcessRequest | None = None,
    service: ProcessingService = Depends(get_processing_service),
    runner: ProcessingRunner = Depends(get_runner),
) -> ProcessAccepted:
    force = payload.force if payload else False
    accepted, overrides = service.enqueue_one(
        case_id,
        evidence_id,
        force=force,
        audio_model=payload.audio_model if payload else None,
        ocr_languages=payload.ocr_languages if payload else None,
    )
    _schedule(background_tasks, runner, case_id, accepted, force=force, options_override=overrides)
    return accepted


@router.post(
    "/evidence/{evidence_id}/retry",
    response_model=ProcessAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_evidence(
    case_id: uuid.UUID,
    evidence_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    service: ProcessingService = Depends(get_processing_service),
    runner: ProcessingRunner = Depends(get_runner),
) -> ProcessAccepted:
    accepted = service.enqueue_retry(case_id, evidence_id)
    _schedule(background_tasks, runner, case_id, accepted, force=False)
    return accepted


# --- in-browser processing (browser_service.py) ------------------------------------
# POST routes, so the case role required is "editor" (app/modules/auth/deps.py).


@router.post(
    "/evidence/{evidence_id}/browser-processing/claim",
    response_model=BrowserClaimOut,
)
def browser_claim(
    case_id: uuid.UUID,
    evidence_id: uuid.UUID,
    payload: BrowserClaimIn | None = None,
    service: BrowserProcessingService = Depends(get_browser_service),
) -> BrowserClaimOut:
    return service.claim(case_id, evidence_id, force=payload.force if payload else False)


@router.post(
    "/evidence/{evidence_id}/browser-processing/heartbeat",
    status_code=status.HTTP_204_NO_CONTENT,
)
def browser_heartbeat(
    case_id: uuid.UUID,
    evidence_id: uuid.UUID,
    payload: BrowserHeartbeatIn,
    service: BrowserProcessingService = Depends(get_browser_service),
) -> None:
    service.heartbeat(case_id, evidence_id, payload.run_number)


@router.post(
    "/evidence/{evidence_id}/browser-processing/result",
    response_model=ProcessingStatusOut,
)
def browser_result(
    case_id: uuid.UUID,
    evidence_id: uuid.UUID,
    payload: BrowserResultIn,
    service: BrowserProcessingService = Depends(get_browser_service),
    processing: ProcessingService = Depends(get_processing_service),
) -> ProcessingStatusOut:
    """Validate and save a browser's result. 200 means it is committed; the returned
    status is read back from the database."""
    service.submit(case_id, evidence_id, payload)
    return processing.status(case_id, evidence_id)


@router.post(
    "/evidence/{evidence_id}/browser-processing/failure",
    response_model=ProcessingStatusOut,
)
def browser_failure(
    case_id: uuid.UUID,
    evidence_id: uuid.UUID,
    payload: BrowserFailureIn,
    service: BrowserProcessingService = Depends(get_browser_service),
    processing: ProcessingService = Depends(get_processing_service),
) -> ProcessingStatusOut:
    service.fail(case_id, evidence_id, payload)
    return processing.status(case_id, evidence_id)


# --- read results ---------------------------------------------------------------


@router.get("/processing", response_model=CaseProcessingSummary)
def case_processing_summary(
    case_id: uuid.UUID,
    service: ProcessingService = Depends(get_processing_service),
) -> CaseProcessingSummary:
    return service.case_summary(case_id)


@router.get("/evidence/{evidence_id}/processing", response_model=ProcessingStatusOut)
def processing_status(
    case_id: uuid.UUID,
    evidence_id: uuid.UUID,
    service: ProcessingService = Depends(get_processing_service),
) -> ProcessingStatusOut:
    return service.status(case_id, evidence_id)


@router.get("/evidence/{evidence_id}/extraction", response_model=ExtractionOut)
def current_extraction(
    case_id: uuid.UUID,
    evidence_id: uuid.UUID,
    service: ProcessingService = Depends(get_processing_service),
) -> ExtractionOut:
    return service.current_extraction(case_id, evidence_id)


@router.get("/evidence/{evidence_id}/extractions", response_model=ExtractionList)
def list_extractions(
    case_id: uuid.UUID,
    evidence_id: uuid.UUID,
    service: ProcessingService = Depends(get_processing_service),
) -> ExtractionList:
    return service.list_extractions(case_id, evidence_id)


@router.get("/evidence/{evidence_id}/extractions/{extraction_id}", response_model=ExtractionOut)
def get_extraction(
    case_id: uuid.UUID,
    evidence_id: uuid.UUID,
    extraction_id: uuid.UUID,
    service: ProcessingService = Depends(get_processing_service),
) -> ExtractionOut:
    return service.get_extraction(case_id, evidence_id, extraction_id)


@router.get("/evidence/{evidence_id}/segments", response_model=SegmentList)
def list_segments(
    case_id: uuid.UUID,
    evidence_id: uuid.UUID,
    service: ProcessingService = Depends(get_processing_service),
    extraction_id: uuid.UUID | None = Query(default=None),
    page: int | None = Query(default=None, ge=1),
    segment_type: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=DEFAULT_SEGMENT_LIMIT, ge=1, le=MAX_SEGMENT_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> SegmentList:
    return service.segments(
        case_id,
        evidence_id,
        extraction_id=extraction_id,
        page=page,
        segment_type=segment_type,
        limit=limit,
        offset=offset,
    )


# --- speech models --------------------------------------------------------------


@audio_router.get("/models", response_model=AudioModelList)
def audio_models(
    service: ProcessingService = Depends(get_processing_service),
) -> AudioModelList:
    """Speech models found on disk. Nothing is loaded or downloaded."""
    return service.audio_models()


# --- OCR languages --------------------------------------------------------------

ocr_router = APIRouter(prefix="/api/ocr", tags=["processing"])


@ocr_router.get("/languages")
def ocr_languages() -> dict:
    """Tesseract language packs installed on this server. Nothing is downloaded."""
    from app.core.config import get_settings
    from app.modules.processing.extractors.ocr_languages import language_report

    return language_report(get_settings().tesseract_cmd, get_settings().tesseract_langs)
