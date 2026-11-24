"""Helpers for calling extractors directly in unit tests."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from app.modules.processing.extractors.base import ExtractionInput, ExtractionResult, Extractor
from app.modules.processing.limits import ExtractionLimits
from app.modules.processing.locators import locator_from_json, locator_to_json


def run(
    extractor: Extractor,
    data: bytes,
    *,
    filename: str = "sample",
    mime: str = "application/octet-stream",
    limits: ExtractionLimits | None = None,
    options: Mapping[str, Any] | None = None,
) -> ExtractionResult:
    return extractor.extract(
        ExtractionInput(
            data=data,
            filename=filename,
            mime_type=mime,
            sha256=hashlib.sha256(data).hexdigest(),
            limits=limits or ExtractionLimits(),
            options=options or {},
        )
    )


def warning_codes(result: ExtractionResult) -> list[str]:
    return [w.code for w in result.warnings]


def assert_locators_valid(result: ExtractionResult) -> None:
    """Every segment carries a locator that survives the JSON round trip."""
    for segment in result.segments:
        assert locator_from_json(locator_to_json(segment.locator)) == segment.locator
