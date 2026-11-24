"""Locators: typed shapes, validation, and promoted-column consistency."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.processing.locators import (
    AudioLocator,
    CsvLocator,
    EmailLocator,
    ImageLocator,
    PdfLocator,
    XlsxLocator,
    locator_from_json,
    locator_to_json,
    promoted_columns,
)

ALL_LOCATORS = [
    PdfLocator(page=3, bbox=(10, 20, 110, 60), page_width=595, page_height=842),
    ImageLocator(bbox=(5, 6, 50, 20), width=800, height=600),
    AudioLocator(start=72.3, end=78.9),
    CsvLocator(row=14, line=15, column="Amount"),
    XlsxLocator(sheet="Payments", row=5, range="A5:F5"),
    EmailLocator(part="header", name="Subject"),
]


@pytest.mark.parametrize("locator", ALL_LOCATORS, ids=lambda x: x.kind)
def test_roundtrip_through_json(locator):
    stored = locator_to_json(locator)
    assert stored["kind"] == locator.kind
    assert locator_from_json(stored) == locator


def test_promoted_columns_for_pdf_and_audio():
    assert promoted_columns(PdfLocator(page=7)) == (7, None, None)
    assert promoted_columns(AudioLocator(start=1.5, end=4.0)) == (None, 1.5, 4.0)


@pytest.mark.parametrize(
    "locator",
    [
        ImageLocator(bbox=(0, 0, 1, 1), width=1, height=1),
        CsvLocator(row=1, line=1),
        XlsxLocator(sheet="S", row=1, range="A1:A1"),
        EmailLocator(part="body_text", index=0),
    ],
)
def test_other_locators_promote_nothing(locator):
    assert promoted_columns(locator) == (None, None, None)


def test_audio_end_before_start_rejected():
    with pytest.raises(ValidationError):
        AudioLocator(start=10, end=5)


def test_pdf_page_must_be_one_based():
    with pytest.raises(ValidationError):
        PdfLocator(page=0)


def test_csv_row_must_be_positive():
    with pytest.raises(ValidationError):
        CsvLocator(row=0, line=1)


def test_unknown_kind_rejected():
    with pytest.raises(ValidationError):
        locator_from_json({"kind": "video", "frame": 3})


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        locator_from_json({"kind": "csv", "row": 1, "line": 1, "surprise": True})


def test_email_part_is_restricted():
    with pytest.raises(ValidationError):
        EmailLocator(part="footer")  # type: ignore[arg-type]
