"""In-browser processing: a signed-in editor's browser runs the OCR or speech engine.

For the file types this server leaves to an external worker (EXTERNAL_WORKER_MIMES:
images, audio, video on the serverless deployment), the browser can do the work
instead. It never decides the outcome by itself; it goes through the same claim and
persistence primitives as the server runner and the worker:

1. ``claim``: ``ProcessingRepository.claim`` (one conditional UPDATE) moves the item
   to ``processing`` and increments its attempts. The new attempt number is the run
   number the browser must quote from now on. A second tab, the worker or the API can
   never hold the same item at the same time.
2. ``heartbeat``: refreshes ``processing_started_at`` for that run only.
3. ``submit``: the result is validated against the stored file (``browser_results``)
   and saved with ``ProcessingRepository.record_success`` in one transaction, only
   while the run still owns the claim. The item reads ``completed`` only after that
   commit. A duplicate or late submission matches nothing and is refused (409).
4. ``fail``: the browser reports why it stopped; ``record_failure`` stores a
   server-chosen message (client text is never stored). The codes are retryable, also
   by a processing worker.

A tab that is closed without reporting simply stops its heartbeats: after
BROWSER_PROCESSING_STALE_SECONDS another browser may claim the item again, and after
PROCESSING_STALE_MINUTES the worker may.

Saved runs are ordinary ``extractions`` / ``extraction_segments`` rows (current run,
``run_status="completed"``), so search, analysis, events, relationships and reports read
them exactly like worker results. Logging: ids, codes and counts only, never text.
"""

from __future__ import annotations

import io
import uuid
import wave
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db_types import utcnow
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.modules.evidence.models import Evidence
from app.modules.processing.browser_results import (
    AUDIO_EXTRACTOR,
    IMAGE_EXTRACTOR,
    VIDEO_EXTRACTOR,
    VIDEO_EXTRACTOR_VERSION,
    BrowserResultError,
    ServerFacts,
    build_audio_result,
    build_image_result,
    build_video_result,
)
from app.modules.processing.browser_schemas import (
    BrowserClaimOut,
    BrowserFailureIn,
    BrowserLimitsOut,
    BrowserResultIn,
)
from app.modules.processing.errors import (
    BROWSER_DECODE_FAILED,
    BROWSER_ENGINE_FAILED,
    BROWSER_OUT_OF_MEMORY,
    BROWSER_RESULT_REJECTED,
    INTERRUPTED,
    STORAGE_MISSING,
)
from app.modules.processing.extractors.base import ExtractionResult
from app.modules.processing.registry import AUDIO_MIMES, IMAGE_MIMES, VIDEO_MIMES
from app.modules.processing.repository import ProcessingRepository
from app.storage.local_store import Storage

logger = get_logger(__name__)

BROWSER_MIMES = frozenset((*IMAGE_MIMES, *AUDIO_MIMES, *VIDEO_MIMES))
HEARTBEAT_SECONDS = 20
# Language data shipped with the web app for browser OCR (public/engines/tesseract).
BROWSER_OCR_LANGUAGE = "eng"

FAILURE_MESSAGES = {
    INTERRUPTED: (
        "In-browser processing stopped before it finished (the tab was closed, reloaded "
        "or left). Nothing was saved. Process the file again."
    ),
    BROWSER_ENGINE_FAILED: (
        "The in-browser OCR or speech engine could not run on this device or browser. "
        "Nothing was saved. Try again in a current desktop Chrome, Edge or Firefox, or "
        "let a processing worker handle the file."
    ),
    BROWSER_DECODE_FAILED: (
        "This browser could not decode the file. That does not mean the file is damaged. "
        "Try another browser (Chrome and Edge decode the most formats), or let a "
        "processing worker handle the file."
    ),
    BROWSER_OUT_OF_MEMORY: (
        "The device ran out of memory while processing the file in the browser. Nothing "
        "was saved. Try a desktop computer, or let a processing worker handle the file."
    ),
}
REJECTED_PREFIX = "The result submitted by the browser was refused: "

_KIND_BY_TYPE = {"image": "image", "audio": "audio", "video": "video"}


def browser_processable(mime_type: str, settings: Settings) -> bool:
    """Whether a browser may process this file type here: only types this server leaves
    to an external worker. Where the server has the engines itself, it processes."""
    return (
        settings.browser_processing_enabled
        and mime_type in BROWSER_MIMES
        and mime_type in settings.external_worker_mimes
    )


def _image_size(data: bytes, max_pixels: int) -> tuple[int, int] | None:
    """(width, height) after the EXIF orientation, without decoding the pixels. None
    when Pillow is unavailable; raises BrowserResultError when the image is unreadable
    or larger than the server allows."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            orientation = image.getexif().get(274)
    except Exception as exc:  # noqa: BLE001 - any parse error: the size is unknown
        raise BrowserResultError("the server could not read the stored image's size") from exc
    if width * height > max_pixels:
        raise BrowserResultError(f"the image is larger than {max_pixels:,} pixels")
    if orientation in (5, 6, 7, 8):  # rotated by 90 or 270 degrees
        width, height = height, width
    return width, height


def _wav_duration(data: bytes) -> float | None:
    try:
        with wave.open(io.BytesIO(data)) as w:
            rate = w.getframerate()
            return w.getnframes() / rate if rate else None
    except Exception:  # noqa: BLE001 - not plain PCM WAV: duration not verifiable here
        return None


class BrowserProcessingService:
    def __init__(self, db: Session, settings: Settings, storage: Storage) -> None:
        self._db = db
        self._repo = ProcessingRepository(db)
        self._settings = settings
        self._storage = storage

    # --- helpers --------------------------------------------------------------------

    def _evidence(self, case_id: uuid.UUID, evidence_id: uuid.UUID) -> Evidence:
        evidence = self._repo.get_evidence(case_id, evidence_id)
        if evidence is None:
            raise NotFoundError("evidence not found")
        return evidence

    def _eligible(self, case_id: uuid.UUID, evidence_id: uuid.UUID) -> Evidence:
        evidence = self._evidence(case_id, evidence_id)
        if not browser_processable(evidence.mime_type, self._settings):
            raise ConflictError(
                "this file type is processed by the server or a processing worker, not "
                "in the browser"
            )
        return evidence

    def _owned(self, evidence: Evidence, run_number: int) -> None:
        if evidence.processing_status != "processing" or evidence.processing_attempts != run_number:
            raise ConflictError(
                "this processing attempt is no longer current (it finished, failed, or "
                "was taken over by another tab or the processing worker)"
            )

    # --- claim / heartbeat ------------------------------------------------------------

    def claim(self, case_id: uuid.UUID, evidence_id: uuid.UUID, *, force: bool) -> BrowserClaimOut:
        evidence = self._eligible(case_id, evidence_id)
        if evidence.processing_status == "completed" and not force:
            raise ConflictError("this file is already processed; re-process it to add a new run")
        now = utcnow()
        stale_cutoff = now - timedelta(seconds=self._settings.browser_processing_stale_seconds)
        if not self._repo.claim(
            case_id, evidence_id, force=force, now=now, stale_cutoff=stale_cutoff
        ):
            raise ConflictError(
                "this file is already being processed (in another tab or by the processing worker)"
            )
        evidence = self._evidence(case_id, evidence_id)
        logger.info(
            "browser processing claimed evidence=%s run=%d",
            evidence.id,
            evidence.processing_attempts,
        )
        s = self._settings
        return BrowserClaimOut(
            evidence_id=evidence.id,
            run_number=evidence.processing_attempts,
            kind=_KIND_BY_TYPE[evidence.evidence_type],  # type: ignore[arg-type]
            mime_type=evidence.mime_type,
            sha256=evidence.sha256,
            byte_size=evidence.byte_size,
            heartbeat_seconds=HEARTBEAT_SECONDS,
            stale_seconds=s.browser_processing_stale_seconds,
            ocr_language=BROWSER_OCR_LANGUAGE,
            limits=BrowserLimitsOut(
                max_extracted_chars=s.max_extracted_chars,
                max_audio_seconds=s.max_audio_seconds,
                max_video_seconds=s.max_video_seconds,
                video_max_frames=s.video_max_frames,
                video_frame_interval_seconds=s.video_frame_interval_seconds,
            ),
        )

    def heartbeat(self, case_id: uuid.UUID, evidence_id: uuid.UUID, run_number: int) -> None:
        self._eligible(case_id, evidence_id)
        if not self._repo.heartbeat(evidence_id, run_number, now=utcnow()):
            raise ConflictError("this processing attempt is no longer current")

    # --- results ----------------------------------------------------------------------

    def _facts(self, evidence: Evidence) -> ServerFacts:
        if evidence.evidence_type not in ("image", "audio"):
            return ServerFacts()
        if not self._storage.exists(evidence.sha256):
            raise LookupError("stored file missing")
        with self._storage.open(evidence.sha256) as fh:
            data = fh.read()
        if evidence.evidence_type == "image":
            return ServerFacts(image_size=_image_size(data, self._settings.max_image_pixels))
        if evidence.mime_type == "audio/wav":
            return ServerFacts(audio_duration=_wav_duration(data))
        return ServerFacts()

    def _build(self, evidence: Evidence, payload: BrowserResultIn) -> ExtractionResult:
        s = self._settings
        result = payload.result
        if result.kind != evidence.evidence_type:
            raise BrowserResultError(
                f"a {result.kind} result was sent for {evidence.evidence_type} evidence"
            )
        if payload.source_sha256 != evidence.sha256:
            raise BrowserResultError("the processed bytes are not the stored file")
        if result.kind == "image":
            return build_image_result(
                result,
                payload.engine,
                self._facts(evidence),
                min_confidence=s.ocr_min_confidence,
                max_chars=s.max_extracted_chars,
            )
        if result.kind == "audio":
            return build_audio_result(
                result,
                payload.engine,
                self._facts(evidence),
                max_audio_seconds=s.max_audio_seconds,
                max_chars=s.max_extracted_chars,
            )
        return build_video_result(
            result,
            payload.engine,
            max_video_seconds=s.max_video_seconds,
            max_frames=s.video_max_frames,
            max_chars=s.max_extracted_chars,
        )

    def _record_failure(
        self, evidence: Evidence, run_number: int, code: str, message: str, duration_ms: int
    ) -> bool:
        extractor = {
            "image": (IMAGE_EXTRACTOR, "browser"),
            "audio": (AUDIO_EXTRACTOR, "browser"),
        }.get(evidence.evidence_type, (VIDEO_EXTRACTOR, VIDEO_EXTRACTOR_VERSION))
        saved = self._repo.record_failure(
            evidence,
            run_number=run_number,
            started_at=utcnow() - timedelta(milliseconds=duration_ms),
            extractor_name=extractor[0],
            extractor_version=extractor[1],
            source_sha256=evidence.sha256,
            error_code=code,
            error_message=message,
            duration_ms=duration_ms,
            # A failed optional re-run must not make good evidence look broken.
            keep_completed=True,
        )
        return saved is not None

    def submit(self, case_id: uuid.UUID, evidence_id: uuid.UUID, payload: BrowserResultIn) -> None:
        evidence = self._eligible(case_id, evidence_id)
        self._owned(evidence, payload.run_number)
        try:
            result = self._build(evidence, payload)
        except LookupError:
            self._record_failure(
                evidence,
                payload.run_number,
                STORAGE_MISSING,
                "The stored file is missing.",
                payload.duration_ms,
            )
            raise BadRequestError("the stored file is missing") from None
        except BrowserResultError as exc:
            reason = str(exc)
            self._record_failure(
                evidence,
                payload.run_number,
                BROWSER_RESULT_REJECTED,
                REJECTED_PREFIX + reason + ".",
                payload.duration_ms,
            )
            logger.warning(
                "browser result refused evidence=%s run=%d", evidence.id, payload.run_number
            )
            raise BadRequestError(f"result refused: {reason}") from None

        saved = self._repo.record_success(
            evidence,
            run_number=payload.run_number,
            started_at=utcnow() - timedelta(milliseconds=payload.duration_ms),
            result=result,
            source_sha256=evidence.sha256,
            duration_ms=payload.duration_ms,
        )
        if saved is None:
            raise ConflictError("this processing attempt is no longer current; nothing was saved")
        logger.info(
            "browser processing completed evidence=%s extractor=%s outcome=%s segments=%d run=%d",
            evidence.id,
            result.extractor,
            result.outcome,
            len(result.segments),
            payload.run_number,
        )

    def fail(self, case_id: uuid.UUID, evidence_id: uuid.UUID, payload: BrowserFailureIn) -> None:
        evidence = self._eligible(case_id, evidence_id)
        self._owned(evidence, payload.run_number)
        if not self._record_failure(
            evidence, payload.run_number, payload.code, FAILURE_MESSAGES[payload.code], 0
        ):
            raise ConflictError("this processing attempt is no longer current")
        logger.info(
            "browser processing failed evidence=%s run=%d code=%s",
            evidence.id,
            payload.run_number,
            payload.code,
        )
