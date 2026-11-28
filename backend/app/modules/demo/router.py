"""Self-service demo: a signed-in user loads their OWN copy of the fictional
"Missing Shipment" case.

The case is owned by the caller and follows the normal permission model (nobody else
can see it). Loading is idempotent and safe to retry (see
``app.demo_seed.provision_demo_case``). Files go into the configured storage exactly
like an upload. Only the formats this server processes itself are queued here (PDF,
CSV, e-mail); with EXTERNAL_WORKER_MIMES set, images, audio and video stay pending for
the local processing worker, which processes and analyses them later.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.core.exceptions import ConflictError, EvidenceXError
from app.core.logging import get_logger
from app.demo_seed import DEMO_TITLE, SeedError, find_user_demo_case, provision_demo_case
from app.modules.analysis.router import get_analysis_runner
from app.modules.analysis.runner import AnalysisRunner
from app.modules.cases.models import Case
from app.modules.demo.schemas import DemoCaseOut, DemoCaseRef, DemoFileOut
from app.modules.evidence.models import Evidence
from app.modules.evidence.router import get_service as get_evidence_service
from app.modules.evidence.service import EvidenceService
from app.modules.processing.router import get_processing_service, get_runner
from app.modules.processing.runner import ProcessingRunner
from app.modules.processing.service import ProcessingService

logger = get_logger(__name__)

router = APIRouter(prefix="/api/demo", tags=["demo"])

SessionFactory = Callable[[], AbstractContextManager[Session]]


class DemoUnavailableError(EvidenceXError):
    status_code = 503
    message = "The demo case is not available on this server."


def get_session_factory() -> SessionFactory:
    """Sessions for work that runs after the response (background tasks)."""
    return SessionLocal


def _process_then_analyse(
    runner: ProcessingRunner,
    analysis: AnalysisRunner,
    session_factory: SessionFactory,
    case_id: uuid.UUID,
    queued: list[uuid.UUID],
) -> None:
    """Background task: process the files this server handles, then analyse the case
    once. Never raises. An analysis that is already running is left alone."""
    from app.modules.analysis.service import AnalysisService

    try:
        runner.run_batch(case_id, queued)
        with session_factory() as db:
            run_id = AnalysisService(db, get_settings()).start_run(case_id, analysis.method).id
        analysis.run(case_id, run_id)
    except ConflictError:
        logger.info("demo analysis skipped: one is already running case=%s", case_id)
    except Exception as exc:  # noqa: BLE001 - a background task must not raise
        logger.error("demo processing failed case=%s error_type=%s", case_id, type(exc).__name__)


@router.get("/missing-shipment", response_model=DemoCaseRef)
def my_demo_case(request: Request, db: Session = Depends(get_db)) -> DemoCaseRef:
    return DemoCaseRef(case_id=find_user_demo_case(db, request.state.user.id))


@router.post("/missing-shipment", response_model=DemoCaseOut)
def load_demo_case(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    evidence: EvidenceService = Depends(get_evidence_service),
    processing: ProcessingService = Depends(get_processing_service),
    runner: ProcessingRunner = Depends(get_runner),
    analysis: AnalysisRunner = Depends(get_analysis_runner),
    session_factory: SessionFactory = Depends(get_session_factory),
) -> DemoCaseOut:
    try:
        result = provision_demo_case(db, evidence, request.state.user)
    except SeedError as exc:
        db.rollback()
        raise DemoUnavailableError() from exc

    # Same decision as "Process all pending": files of the worker's types are skipped
    # (reason "external_worker") and stay pending; completed items are not re-run.
    accepted = processing.enqueue_pending(result.case_id)
    if accepted.queued:
        background_tasks.add_task(
            _process_then_analyse,
            runner,
            analysis,
            session_factory,
            result.case_id,
            list(accepted.queued),
        )

    rows = db.scalars(
        select(Evidence)
        .where(Evidence.case_id == result.case_id)
        .order_by(Evidence.created_at.asc())
    ).all()
    files = [
        DemoFileOut(
            name=e.original_filename,
            processing_status=e.processing_status,
            external_worker=processing.is_external(e),
        )
        for e in rows
    ]
    case = db.get(Case, result.case_id)
    return DemoCaseOut(
        case_id=result.case_id,
        status=result.status,  # type: ignore[arg-type]
        title=case.title if case is not None else DEMO_TITLE,
        files=files,
        queued=len(accepted.queued),
        awaiting_worker=sum(
            1 for f in files if f.external_worker and f.processing_status != "completed"
        ),
    )
