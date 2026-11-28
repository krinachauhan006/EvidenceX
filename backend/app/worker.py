"""Local multimodal processing worker (``python -m app.cli worker``).

The serverless deployment cannot run OCR, speech recognition or video decoding. This
worker runs on a computer that can, and shares the deployment's database and evidence
storage. It is NOT a second API server and there is no new queue: it polls the
existing ``evidence`` rows and processes them with the existing components:

* ``ProcessingRepository.claim`` (one conditional UPDATE) decides who processes an
  item, so the worker and the API can never process the same item at once, and
  saving a result is conditional on still owning that claim;
* ``ProcessingRunner.run_one`` reads the file from storage (the private S3 bucket),
  runs the registered extractor through ``build_executor`` (subprocess isolation and
  the per-item timeout) without holding a database session, and saves the run with
  ``record_success`` / ``record_failure``, which keep the extraction history and the
  single current run;
* ``AnalysisService.start_run`` + ``AnalysisRunner.run`` analyse a case afterwards.

Candidates (oldest first, across all cases):

1. ``pending`` items of a worker MIME type (images, audio, video by default);
2. ``failed`` items of those types whose error is ``dependency_missing`` (the API
   server tried before EXTERNAL_WORKER_MIMES was set) or ``interrupted`` (an engine
   process was stopped, e.g. by Ctrl+C); ``--retry-failed`` widens this to every
   failure code;
3. items of those types stuck in ``processing`` past PROCESSING_STALE_MINUTES (a
   worker that was stopped mid-item);
4. completed PDFs whose current run could not OCR its scanned pages because OCR was
   unavailable where it ran (``ocr_unavailable`` plus outcome ``needs_ocr``, or
   ``partial`` with ``pages_need_ocr``). They are re-run with ``force`` only when the
   PDF extractor is registered here and Tesseract runs here WITH the configured
   language data, and only once: a re-run that again could not OCR, or that failed
   (other than by interruption), is never repeated automatically. A failed re-run
   leaves the item ``completed`` with its previous run current.

Cases are analysed after processing. Which cases need it is re-derived from the
database on every pass (a current run of a worker file type newer than the case's
latest analysis run), so a worker stopped between processing and analysis catches up
on its next start.

While an item runs, a heartbeat refreshes ``processing_started_at`` so the item is not
mistaken for an abandoned one. The heartbeat only touches the row while it is still
``processing`` under this worker's claim (same attempt count).

Logging/printing rule (as in the runner): ids, file names, counts and statuses only;
never file content, credentials, hosts or exception messages.
"""

from __future__ import annotations

import os
import signal
import tempfile
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db_types import as_utc, utcnow
from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.modules.processing.errors import (
    DEPENDENCY_MISSING,
    INTERRUPTED,
    DependencyMissingError,
)
from app.modules.processing.executor import ExtractionExecutor
from app.modules.processing.registry import (
    AUDIO_MIMES,
    IMAGE_MIMES,
    VIDEO_MIMES,
    ExtractorRegistry,
)
from app.modules.processing.repository import ProcessingRepository
from app.modules.processing.runner import ProcessingRunner
from app.storage.local_store import Storage

logger = get_logger(__name__)

SessionFactory = Callable[[], AbstractContextManager[Session]]

# OCR, speech and video: what the serverless deployment cannot process.
DEFAULT_WORKER_MIMES = frozenset((*IMAGE_MIMES, *AUDIO_MIMES, *VIDEO_MIMES))
PDF_MIME = "application/pdf"
DEFAULT_LOCK_FILE = Path(tempfile.gettempdir()) / "evidencex-processing-worker.lock"
# Failure codes the worker retries on its own: the file was never judged.
RECOVERABLE_CODES = frozenset({DEPENDENCY_MISSING, INTERRUPTED})

Reason = Literal["pending", "dependency_missing", "interrupted", "failed", "stale", "scanned_pdf"]


def worker_mime_types(settings: Settings) -> frozenset[str]:
    """EXTERNAL_WORKER_MIMES when set (the same list the deployment skips), else the
    OCR/speech/video types."""
    return settings.external_worker_mimes or DEFAULT_WORKER_MIMES


def _codes(warnings: list[dict[str, Any]] | None) -> set[Any]:
    return {w.get("code") for w in (warnings or []) if isinstance(w, dict)}


def needs_ocr_rerun(outcome: str | None, warnings: list[dict[str, Any]] | None) -> bool:
    """Whether a completed PDF run left scanned pages unread only because OCR was not
    available where it ran. A run where OCR was available but some pages still failed
    (too large, unreadable) is not selected: re-running would give the same result."""
    codes = _codes(warnings)
    if "ocr_unavailable" not in codes:
        return False
    return outcome == "needs_ocr" or (outcome == "partial" and "pages_need_ocr" in codes)


def scanned_pdf_retry_due(current: Any, runs: list[Any]) -> bool:
    """Whether the worker may re-run this PDF: its current run needs OCR, and no
    earlier attempt already tried that. Decided from the stored run history, so it
    holds across worker restarts:

    * another completed run that also needed OCR means a re-run already came out the
      same (for example language data missing where it ran): not again;
    * a failed run after the current one means a re-run already failed (storage,
      timeout, OCR error): not again, unless it was only interrupted.
    """
    if not needs_ocr_rerun(current.outcome, current.warnings):
        return False
    for run in runs:
        if run.id == current.id:
            continue
        if run.run_status == "completed" and needs_ocr_rerun(run.outcome, run.warnings):
            return False
        if (
            run.run_status == "failed"
            and run.run_number > current.run_number
            and run.error_code != INTERRUPTED
        ):
            return False
    return True


def ocr_available(settings: Settings) -> bool:
    """Whether Tesseract runs here AND has the language data of TESSERACT_LANGS
    (checked once per pass, never raises). A runnable Tesseract without the configured
    languages cannot OCR anything: every page would again report ``ocr_unavailable``."""
    from app.modules.processing.extractors.ocr_engine import TesseractEngine
    from app.modules.processing.extractors.ocr_languages import (
        installed_languages,
        validate_languages,
    )
    from app.modules.processing.options import engine_options

    try:
        TesseractEngine().version(engine_options(settings))
        installed = installed_languages(settings.tesseract_cmd)
        _, missing = validate_languages(settings.tesseract_langs or "eng", installed)
        return not missing
    except (DependencyMissingError, ValueError):
        return False
    except Exception:  # noqa: BLE001 - treat any probe error as unavailable
        return False


@dataclass(frozen=True)
class Candidate:
    case_id: Any
    evidence_id: Any
    filename: str
    mime_type: str
    status: str
    reason: Reason
    force: bool = False
    # Identifies the run a scanned-PDF candidate was selected from.
    extraction_id: Any = None


def find_candidates(
    session_factory: SessionFactory,
    settings: Settings,
    *,
    include_scanned_pdfs: bool = True,
    pdf_supported: bool = True,
    retry_failed: bool = False,
    ocr_check: Callable[[], bool] | None = None,
    now: datetime | None = None,
) -> list[Candidate]:
    """Eligible evidence. Reads only: no claim, no write, the session is rolled back.

    ``pdf_supported``: whether the local registry has the PDF extractor; without it a
    scanned PDF is never selected (the re-run could only fail)."""
    now = now or utcnow()
    mimes = worker_mime_types(settings)
    stale_cutoff = now - timedelta(minutes=settings.processing_stale_minutes)
    out: list[Candidate] = []
    with session_factory() as db:
        try:
            repo = ProcessingRepository(db)
            for ev in repo.list_unfinished_by_mime(sorted(mimes), stale_cutoff=stale_cutoff):
                reason: Reason
                if ev.processing_status == "pending":
                    reason = "pending"
                elif ev.processing_status == "processing":
                    reason = "stale"
                elif ev.processing_error_code == DEPENDENCY_MISSING:
                    reason = "dependency_missing"
                elif ev.processing_error_code == INTERRUPTED:
                    reason = "interrupted"
                elif retry_failed:
                    reason = "failed"
                else:
                    continue  # another failure (corrupt file, ...) needs a person
                out.append(
                    Candidate(
                        ev.case_id,
                        ev.id,
                        ev.original_filename,
                        ev.mime_type,
                        ev.processing_status,
                        reason,
                    )
                )
            if include_scanned_pdfs and pdf_supported and PDF_MIME not in mimes:
                pdfs = [
                    (ev, x)
                    for ev, x in repo.list_completed_with_current(PDF_MIME)
                    if needs_ocr_rerun(x.outcome, x.warnings)
                    and scanned_pdf_retry_due(x, repo.list_extractions(ev.case_id, ev.id))
                ]
                if pdfs and (ocr_check or (lambda: ocr_available(settings)))():
                    out.extend(
                        Candidate(
                            ev.case_id,
                            ev.id,
                            ev.original_filename,
                            ev.mime_type,
                            ev.processing_status,
                            "scanned_pdf",
                            force=True,
                            extraction_id=x.id,
                        )
                        for ev, x in pdfs
                    )
                elif pdfs:
                    logger.warning(
                        "worker: %d scanned PDF(s) need OCR but Tesseract or its language "
                        "data (TESSERACT_LANGS) is not available here",
                        len(pdfs),
                    )
        finally:
            db.rollback()
    return out


def cases_needing_analysis(
    session_factory: SessionFactory,
    settings: Settings,
    *,
    include_scanned_pdfs: bool = True,
) -> set[Any]:
    """Cases with a current run of a worker file type (or a scanned PDF this worker
    OCR'd) that is newer than the case's most recent analysis run. Reads only.

    Derived from the database, not remembered, so analysis that never happened
    (worker stopped after processing, crash, ``--once`` with a busy case) is picked
    up on a later pass or start. Any analysis run that started after the extraction
    counts, whatever its outcome: it read that extraction, so a failed analysis is
    not retried in a loop."""
    worker_mimes = worker_mime_types(settings)
    mimes = set(worker_mimes)
    if include_scanned_pdfs:
        mimes.add(PDF_MIME)
    from app.modules.analysis.repository import AnalysisRepository

    newest: dict[Any, datetime] = {}
    with session_factory() as db:
        try:
            rows = ProcessingRepository(db).current_runs_by_mime(sorted(mimes))
            for case_id, mime, created_at, run_number, warnings in rows:
                if mime == PDF_MIME and PDF_MIME not in worker_mimes:
                    # Only PDFs whose current run is a re-run that applied OCR.
                    if run_number < 2 or "ocr_applied" not in _codes(warnings):
                        continue
                stamp = as_utc(created_at)
                if case_id not in newest or stamp > newest[case_id]:
                    newest[case_id] = stamp
            latest = AnalysisRepository(db).latest_run_start_by_case(newest)
        finally:
            db.rollback()
    return {
        case_id
        for case_id, stamp in newest.items()
        if latest.get(case_id) is None or as_utc(latest[case_id]) < stamp
    }


class Heartbeat:
    """Refreshes ``processing_started_at`` every ``interval`` seconds for one claim.

    Uses its own database session. Stops by itself as soon as the row is no longer
    ``processing`` under this claim (finished, failed, or reclaimed by someone else).
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        evidence_id: Any,
        run_number: int,
        interval: float,
    ) -> None:
        self._session_factory = session_factory
        self._evidence_id = evidence_id
        self._run_number = run_number
        self._interval = max(0.01, float(interval))
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="worker-heartbeat", daemon=True)
        self.beats = 0
        self.lost = False  # True once the claim was no longer ours

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=10)

    def beat(self) -> bool:
        with self._session_factory() as db:
            ok = ProcessingRepository(db).heartbeat(
                self._evidence_id, self._run_number, now=utcnow()
            )
        if ok:
            self.beats += 1
        else:
            self.lost = True
        return ok

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                if not self.beat():
                    return
            except Exception as exc:  # noqa: BLE001 - a missed beat is retried next time
                logger.warning(
                    "worker heartbeat failed evidence=%s error_type=%s",
                    self._evidence_id,
                    type(exc).__name__,
                )


class WorkerLockError(RuntimeError):
    """Another worker already holds the lock file."""


class WorkerLock:
    """An exclusive OS-level lock on a file, so only one worker runs per machine.

    The operating system releases the lock when the process ends, even after a crash,
    so a leftover file never blocks the next start."""

    def __init__(self, path: Path | str = DEFAULT_LOCK_FILE) -> None:
        self.path = Path(path)
        self._fh: Any = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")  # noqa: SIM115 - held for the process lifetime
        try:
            fh.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            raise WorkerLockError(
                f"another EvidenceX processing worker is already running (lock: {self.path})"
            ) from None
        if os.name != "nt":
            fh.truncate(0)
            fh.write(f"{os.getpid()}\n".encode())
            fh.flush()
        self._fh = fh

    def release(self) -> None:
        fh, self._fh = self._fh, None
        if fh is None:
            return
        try:
            fh.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            fh.close()

    def __enter__(self) -> WorkerLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


@dataclass
class PassReport:
    candidates: int = 0
    results: list[tuple[Candidate, str]] = field(default_factory=list)
    analysis: dict[Any, str] = field(default_factory=dict)  # case_id -> outcome
    interrupted: bool = False

    def count(self, status: str) -> int:
        return sum(1 for _, s in self.results if s == status)


class ProcessingWorker:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        settings: Settings,
        storage: Storage,
        registry: ExtractorRegistry,
        executor: ExtractionExecutor,
        analysis_runner: Any = None,
        analyse: bool = True,
        include_scanned_pdfs: bool = True,
        retry_failed: bool = False,
        heartbeat_seconds: float = 60.0,
        ocr_check: Callable[[], bool] | None = None,
        stop: threading.Event | None = None,
        emit: Callable[[str], None] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._registry = registry
        self._runner = ProcessingRunner(
            session_factory=session_factory,
            storage=storage,
            registry=registry,
            executor=executor,
            settings=settings,
        )
        self._analysis = analysis_runner
        self._analyse = analyse
        self._include_pdfs = include_scanned_pdfs
        self._retry_failed = retry_failed
        self._heartbeat_seconds = heartbeat_seconds
        self._ocr_check = ocr_check
        self.stop = stop or threading.Event()
        self._emit = emit or (lambda _m: None)
        # Items this process already failed, and scanned PDFs it already re-ran (keyed
        # by evidence id, which a re-run does not change): never retried by the same
        # process, so a missing engine cannot cause a loop of runs. The stored run
        # history additionally stops repeats across restarts (scanned_pdf_retry_due).
        self._gave_up: set[Any] = set()
        self._pdf_done: set[Any] = set()
        # Cases whose analysis could not start (already running): retried next pass.
        # Cases are also rediscovered from the database (cases_needing_analysis).
        self._analysis_due: set[Any] = set()
        # Cases whose analysis could not even be started for another reason: not
        # retried by this process (avoids an error on every pass).
        self._analysis_failed: set[Any] = set()

    # --- discovery ---------------------------------------------------------------

    def candidates(self) -> list[Candidate]:
        found = find_candidates(
            self._session_factory,
            self._settings,
            include_scanned_pdfs=self._include_pdfs,
            pdf_supported=self._registry.supports(PDF_MIME),
            retry_failed=self._retry_failed,
            ocr_check=self._ocr_check,
        )
        return [
            c
            for c in found
            if c.evidence_id not in self._gave_up
            and not (c.reason == "scanned_pdf" and c.evidence_id in self._pdf_done)
        ]

    def cases_to_analyse(self) -> set[Any]:
        return cases_needing_analysis(
            self._session_factory, self._settings, include_scanned_pdfs=self._include_pdfs
        )

    # --- one pass ------------------------------------------------------------------

    def run_pass(self) -> PassReport:
        report = PassReport()
        todo = self.candidates()
        report.candidates = len(todo)
        processed_cases: set[Any] = set()
        for cand in todo:
            if self.stop.is_set():
                report.interrupted = True
                break
            status = self.process(cand)
            report.results.append((cand, status))
            self._emit(f"  {cand.filename} [{cand.reason}]: {status}")
            if status == "completed":
                processed_cases.add(cand.case_id)
            elif status == "failed":
                self._gave_up.add(cand.evidence_id)
            if cand.reason == "scanned_pdf" and status not in ("skipped", "superseded"):
                self._pdf_done.add(cand.evidence_id)
        if self._analyse and self._analysis is not None:
            due = processed_cases | self._analysis_due
            if not self.stop.is_set():
                try:
                    due |= self.cases_to_analyse()
                except Exception as exc:  # noqa: BLE001 - analysis discovery is best effort
                    logger.error(
                        "worker analysis discovery failed error_type=%s", type(exc).__name__
                    )
            due -= self._analysis_failed
            for case_id in sorted(due, key=str):
                if self.stop.is_set():
                    report.interrupted = True
                    self._analysis_due |= due - set(report.analysis)
                    break
                outcome = self.analyse_case(case_id)
                report.analysis[case_id] = outcome
                if outcome == "conflict":
                    self._analysis_due.add(case_id)
                else:
                    self._analysis_due.discard(case_id)
                    if outcome == "error":
                        self._analysis_failed.add(case_id)
        return report

    def process(self, cand: Candidate) -> str:
        """Claim and process one item. Returns the runner status, or 'error' when the
        runner itself crashed (the item is then left for the stale-reclaim)."""
        beats: list[Heartbeat] = []

        def on_claimed(run_number: int) -> None:
            hb = Heartbeat(
                self._session_factory, cand.evidence_id, run_number, self._heartbeat_seconds
            )
            beats.append(hb)
            hb.start()

        try:
            return self._runner.run_one(
                cand.case_id,
                cand.evidence_id,
                cand.force,
                None,
                on_claimed=on_claimed,
                # An optional OCR re-run must never make a good PDF look broken.
                keep_completed_on_failure=cand.reason == "scanned_pdf",
            )
        except Exception as exc:  # noqa: BLE001 - one item must not stop the worker
            logger.error(
                "worker item crashed evidence=%s error_type=%s",
                cand.evidence_id,
                type(exc).__name__,
            )
            return "error"
        finally:
            for hb in beats:
                hb.stop()

    def analyse_case(self, case_id: Any) -> str:
        """'completed', 'conflict' (another analysis is running), 'missing' (case
        deleted) or 'error'. Never raises."""
        from app.modules.analysis.service import AnalysisService

        try:
            with self._session_factory() as db:
                try:
                    run = AnalysisService(db, self._settings).start_run(
                        case_id, self._analysis.method
                    )
                except ConflictError:
                    return "conflict"
                except NotFoundError:
                    return "missing"
                run_id = run.id
            self._analysis.run(case_id, run_id)
            return "completed"
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "worker analysis failed case=%s error_type=%s", case_id, type(exc).__name__
            )
            return "error"

    # --- loop ------------------------------------------------------------------------

    def run_forever(self, poll_seconds: float) -> int:
        """Poll until ``stop`` is set. Returns the number of passes."""
        passes = 0
        while not self.stop.is_set():
            report = self.run_pass()
            passes += 1
            if report.results or report.analysis:
                self._emit(describe_pass(report))
            if self.stop.wait(max(0.0, poll_seconds)):
                break
        return passes


def describe_pass(report: PassReport, *, continuous: bool = True) -> str:
    """One summary line. ``continuous=False`` (``--once``): nothing is retried by this
    process, so a busy case is reported as left for a later run."""
    parts = [
        f"{report.candidates} candidate(s)",
        f"{report.count('completed')} completed",
        f"{report.count('failed')} failed",
        f"{report.count('skipped')} skipped (claimed elsewhere or no longer eligible)",
    ]
    if report.count("superseded"):
        parts.append(f"{report.count('superseded')} discarded (a newer attempt took over the item)")
    if report.count("error"):
        parts.append(f"{report.count('error')} error(s)")
    if report.analysis:
        done = sum(1 for v in report.analysis.values() if v == "completed")
        busy = sum(1 for v in report.analysis.values() if v == "conflict")
        if continuous:
            busy_text = f"{busy} already running (retried next pass)"
        else:
            busy_text = (
                f"{busy} already running (not retried by --once; the next worker run analyses it)"
            )
        parts.append(f"analysis: {done} case(s) analysed, {busy_text}")
    if report.interrupted:
        parts.append("stopped early on request")
    return "; ".join(parts)


def install_stop_handlers(stop: threading.Event, emit: Callable[[str], None]) -> Callable[[], None]:
    """First Ctrl+C (or Ctrl+Break / SIGTERM): finish the current item, then stop.
    Second Ctrl+C: stop immediately (the item is reclaimed later as stale). Returns a
    function that restores the previous handlers."""
    names = ["SIGINT", "SIGTERM", "SIGBREAK"]
    previous: dict[int, Any] = {}

    def handler(signum: int, _frame: Any) -> None:
        if stop.is_set():
            signal.signal(signal.SIGINT, signal.default_int_handler)
            raise KeyboardInterrupt
        stop.set()
        emit(
            "Stop requested: finishing the current item, then exiting. "
            "Press Ctrl+C again to stop immediately."
        )

    for name in names:
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            previous[sig] = signal.signal(sig, handler)
        except (ValueError, OSError):  # not the main thread / unsupported here
            continue

    def restore() -> None:
        for sig, old in previous.items():
            try:
                signal.signal(sig, old)
            except (ValueError, OSError):
                pass

    return restore


def engine_report(settings: Settings) -> list[str]:
    """Which local engines are usable (names and yes/no only)."""
    import importlib.util

    from app.modules.processing.audio_models import available_model_names

    try:
        models = set(available_model_names(settings.whisper_model_dir))
    except Exception:  # noqa: BLE001
        models = set()
    return [
        f"Tesseract OCR with TESSERACT_LANGS='{settings.tesseract_langs}': "
        f"{'yes' if ocr_available(settings) else 'NO'}",
        f"PyAV (audio/video decoding): {'yes' if importlib.util.find_spec('av') else 'NO'}",
        f"faster-whisper: {'yes' if importlib.util.find_spec('faster_whisper') else 'NO'}",
        f"speech model '{settings.whisper_model_size}': "
        f"{'yes' if settings.whisper_model_size in models else 'NO'}",
        f"processing isolation: {settings.processing_isolation}",
    ]
