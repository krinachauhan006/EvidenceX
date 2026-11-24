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
