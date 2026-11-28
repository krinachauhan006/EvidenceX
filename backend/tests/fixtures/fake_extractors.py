"""Fake extractors for failure-isolation and retry tests."""

from __future__ import annotations

from app.modules.processing.extractors.base import (
    ExtractionInput,
    ExtractionResult,
    Extractor,
)


class FailingExtractor:
    """Always raises the given exception."""

    name = "fake-fail"
    version = "0"

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls = 0

    def extract(self, inp: ExtractionInput) -> ExtractionResult:
        self.calls += 1
        raise self._exc


class FlakyExtractor:
    """Raises on the first ``fail_times`` calls, then delegates to a real extractor."""

    name = "fake-flaky"
    version = "0"

    def __init__(self, exc: Exception, delegate: Extractor, fail_times: int = 1) -> None:
        self._exc = exc
        self._delegate = delegate
        self._remaining = fail_times
        self.calls = 0

    def extract(self, inp: ExtractionInput) -> ExtractionResult:
        self.calls += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise self._exc
        return self._delegate.extract(inp)


class FakeOcrExtractor:
    """Succeeds with one OCR-style line, without Tesseract. ``started``/``release``
    let a test hold the extraction open (to observe the heartbeat) and ``delay``
    simulates a slow engine."""

    name = "fake-ocr"
    version = "1"

    def __init__(
        self,
        text: str = "Gate log: the truck arrived at 10:34 on 12 October 2026.",
        *,
        delay: float = 0.0,
        started=None,  # noqa: ANN001 - threading.Event | None
        release=None,  # noqa: ANN001 - threading.Event | None
    ) -> None:
        self.text = text
        self.delay = delay
        self.started = started
        self.release = release
        self.calls = 0

    def extract(self, inp: ExtractionInput) -> ExtractionResult:
        import time

        from app.modules.processing.extractors.base import SegmentDraft
        from app.modules.processing.locators import ImageLocator, PdfLocator

        self.calls += 1
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            self.release.wait(timeout=30)
        if self.delay:
            time.sleep(self.delay)
        if inp.mime_type == "application/pdf":
            locator = PdfLocator(page=1, bbox=[0, 0, 100, 20], page_width=612, page_height=792)
            segment_type = "pdf_text_block"
        else:
            locator = ImageLocator(bbox=[0, 0, 100, 20], width=200, height=100)
            segment_type = "ocr_line"
        return ExtractionResult(
            self.name,
            self.version,
            "ok",
            [SegmentDraft(segment_type, self.text, locator, engine_confidence=0.9)],
        )
