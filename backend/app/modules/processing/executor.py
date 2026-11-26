"""Where an extractor actually runs.

``InlineExecutor`` runs it in the current worker thread.

``SubprocessExecutor`` (Phase 2) runs it in a separate, short-lived process with a
hard wall-clock timeout: a hostile or broken file that hangs or crashes a native
parser (PDF, video) is killed without affecting the API process or other items. The
extractor and its input are pickled to the child; expected ``ExtractionError``s come
back as (code, message) and are re-raised with the same code. Formats listed in
``ISOLATED_MIMES`` are isolated; everything else stays inline, because speech models
are expensive to load per process.
"""

from __future__ import annotations

import multiprocessing as mp
from typing import Any, Protocol

from app.modules.processing.errors import ExtractionError, ExtractionTimeoutError
from app.modules.processing.extractors.base import (
    ExtractionInput,
    ExtractionResult,
    Extractor,
)

ISOLATED_MIMES = frozenset({"application/pdf", "video/mp4", "video/quicktime", "video/webm"})


class ExtractionExecutor(Protocol):
    def run(self, extractor: Extractor, inp: ExtractionInput) -> ExtractionResult: ...


class InlineExecutor:
    def run(self, extractor: Extractor, inp: ExtractionInput) -> ExtractionResult:
        return extractor.extract(inp)


def _child(extractor: Extractor, inp: ExtractionInput) -> tuple[str, Any]:
    try:
        return "ok", extractor.extract(inp)
    except ExtractionError as exc:
        return "error", (exc.code, exc.message)
    except Exception as exc:  # noqa: BLE001 - reported to the parent by type only
        return "crash", type(exc).__name__


class _RemoteError(ExtractionError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SubprocessExecutor:
    def __init__(self, timeout_seconds: float, *, mimes: frozenset[str] = ISOLATED_MIMES):
        self._timeout = float(timeout_seconds)
        self._mimes = mimes
        self._inline = InlineExecutor()

    def run(self, extractor: Extractor, inp: ExtractionInput) -> ExtractionResult:
        if inp.mime_type not in self._mimes:
            return self._inline.run(extractor, inp)
        ctx = mp.get_context("spawn")
        pool = ctx.Pool(processes=1, maxtasksperchild=1)
        try:
            pending = pool.apply_async(_child, (extractor, inp))
            try:
                status, value = pending.get(timeout=self._timeout)
            except mp.TimeoutError:
                pool.terminate()
                raise ExtractionTimeoutError(
                    f"Extraction exceeded {int(self._timeout)} s and the worker process was "
                    "stopped."
                ) from None
        finally:
            pool.terminate()
            pool.join()
        if status == "ok":
            return value
        if status == "error":
            raise _RemoteError(*value)
        raise RuntimeError(f"extractor process crashed ({value})")


def build_executor(settings: Any) -> ExtractionExecutor:
    if getattr(settings, "processing_isolation", "inline") == "subprocess":
        return SubprocessExecutor(settings.processing_item_timeout_seconds)
    return InlineExecutor()
