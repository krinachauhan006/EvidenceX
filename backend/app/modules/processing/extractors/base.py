"""Extractor contract.

An extractor is a pure function of bytes. It knows nothing about the database,
storage or HTTP, which keeps it easy to test and safe to move into a subprocess.
Extracted text is untrusted data: extractors store it, they never interpret it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.modules.processing.limits import ExtractionLimits
from app.modules.processing.locators import Locator

Outcome = Literal["ok", "partial", "needs_ocr", "empty"]
OUTCOMES: tuple[str, ...] = ("ok", "partial", "needs_ocr", "empty")


@dataclass(frozen=True)
class ExtractionInput:
    data: bytes
    filename: str  # display only; never used to build a path
    mime_type: str
    sha256: str
    limits: ExtractionLimits
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionWarning:
    code: str
    message: str
    detail: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.detail is not None:
            out["detail"] = self.detail
        return out


@dataclass
class SegmentDraft:
    segment_type: str
    text: str | None
    locator: Locator
    data: dict[str, Any] | None = None
    # Engine-reported confidence in [0, 1] (OCR, speech). Not a statement of
    # factual accuracy, and separate from claim-level extraction confidence.
    engine_confidence: float | None = None
    language: str | None = None


@dataclass
class ExtractionResult:
    extractor: str
    extractor_version: str
    outcome: Outcome
    segments: list[SegmentDraft]
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[ExtractionWarning] = field(default_factory=list)


class Extractor(Protocol):
    name: str
    version: str

    def extract(self, inp: ExtractionInput) -> ExtractionResult: ...
