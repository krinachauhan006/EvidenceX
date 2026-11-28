"""Background processing runner.

Runs after the HTTP response has been sent, with its OWN database sessions (the
request's session is closed by then). Each item goes through three steps:

1. **Claim** (short session): one conditional UPDATE wins the item, the few fields
   the run needs are copied, and the session is closed again.
2. **Extract** (no database session): the expensive part (OCR, speech, video can take
   many minutes) never holds a connection or an open transaction.
3. **Save** (new short session): the run and all its segments are persisted in one
   transaction, and only while this attempt still owns the claim (see
   ``ProcessingRepository.record_success``).

A failure marks only that item failed; it never stops the rest of the batch or the
application.

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
from dataclasses import dataclass
from datetime import datetime, timedelta
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


@dataclass(frozen=True)
class ClaimedItem:
    """A detached copy of what one claimed run needs. Holding this instead of an ORM
    object means no database session stays open while the extractor runs."""

    id: uuid.UUID
    case_id: uuid.UUID
    run_number: int
    sha256: str
    mime_type: str
    filename: str
    started_at: datetime


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

    def claim(
        self, case_id: uuid.UUID, evidence_id: uuid.UUID, *, force: bool
    ) -> ClaimedItem | None:
        """Win the item atomically and return a detached copy of it, or None when it
        is not eligible (or was deleted). The session is closed before returning."""
        with self._session_factory() as db:
            repo = ProcessingRepository(db)
            now = utcnow()
            stale_cutoff = now - timedelta(minutes=self._settings.processing_stale_minutes)
            if not repo.claim(
                case_id, evidence_id, force=force, now=now, stale_cutoff=stale_cutoff
            ):
                logger.info("processing skipped (not eligible) evidence=%s", evidence_id)
                return None
            evidence = repo.get_evidence(case_id, evidence_id)
            if evidence is None:  # deleted right after the claim
                db.commit()
                return None
            item = ClaimedItem(
                id=evidence.id,
                case_id=evidence.case_id,
                run_number=evidence.processing_attempts,
                sha256=evidence.sha256,
                mime_type=evidence.mime_type,
                filename=evidence.original_filename,
                started_at=now,
            )
            # End the read transaction now (nothing is pending, so this writes
            # nothing): no transaction may stay open during extraction.
            db.commit()
            return item

    def run_one(
        self,
        case_id: uuid.UUID,
        evidence_id: uuid.UUID,
        force: bool = False,
        options_override: dict[str, Any] | None = None,
        on_claimed: Callable[[int], None] | None = None,
        *,
        keep_completed_on_failure: bool = False,
    ) -> str:
        """Process a single item. Returns 'completed', 'failed', 'skipped' (not
        eligible, or deleted) or 'superseded' (the claim was lost to a newer attempt
        while this one ran; nothing was saved).

        ``on_claimed(run_number)`` is called once this runner has won the claim, before
        extraction starts (the processing worker starts its heartbeat there). An error
        raised by it is logged and ignored.

        ``keep_completed_on_failure``: if this (optional) re-run fails while the item
        still has a successful current run, the item returns to ``completed`` instead
        of ``failed``; the failed run is kept in the history."""
        item = self.claim(case_id, evidence_id, force=force)
        if item is None:
            return "skipped"

        if on_claimed is not None:
            try:
                on_claimed(item.run_number)
            except Exception as exc:  # noqa: BLE001 - a hook must not stop processing
                logger.warning(
                    "on_claimed hook failed evidence=%s error_type=%s",
                    evidence_id,
                    type(exc).__name__,
                )

        started = time.perf_counter()
        extractor = self._registry.get(item.mime_type)
        extractor_name = getattr(extractor, "name", "none")
        extractor_version = getattr(extractor, "version", "0")

        result: ExtractionResult | None = None
        error_code = INTERNAL_ERROR
        error_message = "Unexpected error during extraction."
        try:
            if extractor is None:
                raise UnsupportedContentError("No extractor is available for this file type.")
            data = self._read_blob(item.sha256)
            inp = ExtractionInput(
                data=data,
                filename=item.filename,
                mime_type=item.mime_type,
                sha256=item.sha256,
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

        with self._session_factory() as db:
            repo = ProcessingRepository(db)
            if result is not None:
                try:
                    saved = repo.record_success(
                        item,
                        run_number=item.run_number,
                        started_at=item.started_at,
                        result=result,
                        source_sha256=item.sha256,
                        duration_ms=duration_ms,
                    )
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
                else:
                    if saved is None:
                        return self._lost(repo, item)
                    logger.info(
                        "processing completed evidence=%s extractor=%s outcome=%s "
                        "segments=%d run=%d ms=%d",
                        evidence_id,
                        extractor_name,
                        result.outcome,
                        len(result.segments),
                        item.run_number,
                        duration_ms,
                    )
                    return "completed"

            try:
                saved = repo.record_failure(
                    item,
                    run_number=item.run_number,
                    started_at=item.started_at,
                    extractor_name=extractor_name,
                    extractor_version=extractor_version,
                    source_sha256=item.sha256,
                    error_code=error_code,
                    error_message=error_message,
                    duration_ms=duration_ms,
                    keep_completed=keep_completed_on_failure,
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
            if saved is None:
                return self._lost(repo, item)
        logger.info(
            "processing failed evidence=%s extractor=%s code=%s run=%d",
            evidence_id,
            extractor_name,
            error_code,
            item.run_number,
        )
        return "failed"

    def _lost(self, repo: ProcessingRepository, item: ClaimedItem) -> str:
        """Nothing was saved because the claim is gone: 'skipped' when the item was
        deleted, 'superseded' when a newer attempt owns it (its result stands)."""
        if repo.get_evidence(item.case_id, item.id) is None:
            return "skipped"
        logger.warning(
            "processing result discarded: claim lost to a newer attempt evidence=%s run=%d",
            item.id,
            item.run_number,
        )
        return "superseded"

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
