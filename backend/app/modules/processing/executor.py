"""Where an extractor actually runs.

``InlineExecutor`` runs it in the current worker thread. The protocol is the seam
for a future subprocess executor (hard timeout, crash isolation) that would not
require any change to the extractors.
"""

from __future__ import annotations

from typing import Protocol

from app.modules.processing.extractors.base import (
    ExtractionInput,
    ExtractionResult,
    Extractor,
)


class ExtractionExecutor(Protocol):
    def run(self, extractor: Extractor, inp: ExtractionInput) -> ExtractionResult: ...


class InlineExecutor:
    def run(self, extractor: Extractor, inp: ExtractionInput) -> ExtractionResult:
        return extractor.extract(inp)
