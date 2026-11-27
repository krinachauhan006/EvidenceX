"""Background processing runner.

Runs after the HTTP response has been sent, with its OWN database session (the
request's session is closed by then). Each item is claimed atomically, extracted,
and persisted in one transaction. A failure marks only that item failed; it never
stops the rest of the batch or the application.

Logging rule: ids, extractor names, outcomes, counts and durations only. Never log
extracted text, file bytes, filesystem paths or exception messages (which can echo
file content).
"""

from __future__ import annotations

import os
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db_types import utcnow
from app.core.logging import get_logger
from app.modules.processing.errors import (
    DEPENDENCY_MISSING,
    INTERNAL_ERROR,
    ExtractionError,
    StorageMissingError,
    UnsupportedContentError,
)
from app.modules.processing.executor import ExtractionExecutor, build_executor
from app.modules.processing.extractors.base import (
    OUTCOMES,
    ExtractionInput,
    ExtractionResult,
)
from app.modules.processing.limits import ExtractionLimits
from app.modules.processing.options import engine_options
from app.modules.processing.registry import ExtractorRegistry, get_registry
from app.modules.processing.repository import ProcessingRepository
from app.storage.factory import build_storage
from app.storage.local_store import Storage

logger = get_logger(__name__)

# Shown instead of an install hint when an engine is missing on a Vercel deployment,
# where the user cannot install system software.
SERVERLESS_ENGINE_MESSAGE = (
    "This file type needs a processing engine (OCR, video decoding or speech "
    "recognition) that is not available on this serverless deployment. The file is "
    "stored safely and can still be downloaded. To extract it, process it on a full "
    "EvidenceX installation (Docker or local) connected to the same database and storage."
)

SessionFactory = Callable[[], AbstractContextManager[Session]]

_GATES: dict[int, threading.BoundedSemaphore] = {}
_GATES_LOCK = threading.Lock()


def get_gate(max_concurrency: int) -> threading.BoundedSemaphore:
    """Process-wide limit on simultaneous heavy extractions."""
    with _GATES_LOCK:
        gate = _GATES.get(max_concurrency)
        if gate is None:
            gate = _GATES[max_concurrency] = threading.BoundedSemaphore(max_concurrency)
        return gate


def _where(exc: BaseException) -> str:
    """Innermost source location of an exception, without its message."""
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return "unknown"
    last = frames[-1]
    return f"{os.path.basename(last.filename)}:{last.lineno}"


class ProcessingRunner:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        storage: Storage,
        registry: ExtractorRegistry,
        executor: ExtractionExecutor,
        settings: Settings,
        gate: threading.BoundedSemaphore | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._registry = registry
        self._executor = executor
        self._settings = settings
        self._gate = gate or get_gate(settings.processing_max_concurrency)

    def run_batch(
        self,
        case_id: uuid.UUID,
        evidence_ids: list[uuid.UUID],
        force: bool = False,
        options_override: dict[str, Any] | None = None,
    ) -> None:
        """Process items one after another. Never raises."""
        for evidence_id in evidence_ids:
            try:
                self.run_one(case_id, evidence_id, force, options_override)
            except Exception as exc:  # noqa: BLE001 - one item must not stop the batch
                logger.error(
                    "batch item crashed evidence=%s error_type=%s at %s",
                    evidence_id,
                    type(exc).__name__,
                    _where(exc),
                )

    def run_one(
        self,
        case_id: uuid.UUID,
        evidence_id: uuid.UUID,
        force: bool = False,
        options_override: dict[str, Any] | None = None,
    ) -> str:
        """Process a single item. Returns 'completed', 'failed' or 'skipped'."""
        with self._session_factory() as db:
            repo = ProcessingRepository(db)
            now = utcnow()
            stale_cutoff = now - timedelta(minutes=self._settings.processing_stale_minutes)

            claimed = repo.claim(
                case_id, evidence_id, force=force, now=now, stale_cutoff=stale_cutoff
            )
            if not claimed:
                logger.info("processing skipped (not eligible) evidence=%s", evidence_id)
                return "skipped"

            evidence = repo.get_evidence(case_id, evidence_id)
            if evidence is None:  # deleted right after the claim
                return "skipped"

            run_number = evidence.processing_attempts
            sha256 = evidence.sha256
            started = time.perf_counter()
            extractor = self._registry.get(evidence.mime_type)
            extractor_name = getattr(extractor, "name", "none")
            extractor_version = getattr(extractor, "version", "0")

            result: ExtractionResult | None = None
            error_code = INTERNAL_ERROR
            error_message = "Unexpected error during extraction."
            try:
                if extractor is None:
                    raise UnsupportedContentError("No extractor is available for this file type.")
                data = self._read_blob(sha256)
                inp = ExtractionInput(
                    data=data,
                    filename=evidence.original_filename,
                    mime_type=evidence.mime_type,
                    sha256=sha256,
                    limits=ExtractionLimits.from_settings(self._settings),
                    options={**engine_options(self._settings), **(options_override or {})},
                )
                with self._gate:
                    result = self._executor.run(extractor, inp)
                _check_result(result)
            except ExtractionError as exc:
                result, error_code, error_message = None, exc.code, exc.message
                if error_code == DEPENDENCY_MISSING and getattr(self._settings, "vercel", False):
                    error_message = SERVERLESS_ENGINE_MESSAGE
            except Exception as exc:  # noqa: BLE001 - isolate any extractor crash
                result = None
                logger.error(
                    "extraction crashed evidence=%s extractor=%s error_type=%s at %s",
                    evidence_id,
                    extractor_name,
                    type(exc).__name__,
                    _where(exc),
                )

            duration_ms = int((time.perf_counter() - started) * 1000)

            if result is not None:
                try:
                    repo.record_success(
                        evidence,
                        run_number=run_number,
                        started_at=now,
                        result=result,
                        source_sha256=sha256,
                        duration_ms=duration_ms,
                    )
                    logger.info(
                        "processing completed evidence=%s extractor=%s outcome=%s "
                        "segments=%d run=%d ms=%d",
                        evidence_id,
                        extractor_name,
                        result.outcome,
                        len(result.segments),
                        run_number,
                        duration_ms,
                    )
                    return "completed"
                except Exception as exc:  # noqa: BLE001 - saving failed: roll back, record failure
                    db.rollback()
                    logger.error(
                        "saving results failed evidence=%s error_type=%s at %s",
                        evidence_id,
                        type(exc).__name__,
                        _where(exc),
                    )
                    error_code = INTERNAL_ERROR
                    error_message = "The extraction result could not be saved."

            try:
                evidence = repo.get_evidence(case_id, evidence_id)
                if evidence is None:
                    return "skipped"
                repo.record_failure(
                    evidence,
                    run_number=run_number,
                    started_at=now,
                    extractor_name=extractor_name,
                    extractor_version=extractor_version,
                    source_sha256=sha256,
                    error_code=error_code,
                    error_message=error_message,
                    duration_ms=duration_ms,
                )
            except Exception as exc:  # noqa: BLE001
                # The item stays "processing" and becomes reclaimable after the
                # stale timeout.
                db.rollback()
                logger.error(
                    "could not record failure evidence=%s error_type=%s at %s",
                    evidence_id,
                    type(exc).__name__,
                    _where(exc),
                )
                return "failed"
            logger.info(
                "processing failed evidence=%s extractor=%s code=%s run=%d",
                evidence_id,
                extractor_name,
                error_code,
                run_number,
            )
            return "failed"

    def _read_blob(self, sha256: str) -> bytes:
        if not self._storage.exists(sha256):
            raise StorageMissingError("The stored file is missing.")
        with self._storage.open(sha256) as fh:
            return fh.read()


def _check_result(result: ExtractionResult) -> None:
    if result.outcome not in OUTCOMES:
        raise ExtractionError("The extractor returned an invalid outcome.")


def build_default_runner() -> ProcessingRunner:
    """Runner wired for production use. Imported lazily to keep module import light."""
    from app.core.database import SessionLocal

    settings = get_settings()
    return ProcessingRunner(
        session_factory=SessionLocal,
        storage=build_storage(settings),
        registry=get_registry(),
        # PROCESSING_ISOLATION=subprocess (default): PDF and video parse in a child
        # process with a hard timeout; other formats stay inline.
        executor=build_executor(settings),
        settings=settings,
    )
