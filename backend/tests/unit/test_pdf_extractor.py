"""PDF extractor (PyMuPDF): text blocks, scanned pages, OCR fallback, hostile input."""

from __future__ import annotations

import pytest

from app.modules.processing.errors import CorruptFileError, PasswordRequiredError
from app.modules.processing.extractors.ocr_engine import find_tesseract
from app.modules.processing.extractors.pdf import PdfExtractor
from app.modules.processing.limits import ExtractionLimits
from tests.fixtures.extraction import assert_locators_valid, run, warning_codes
from tests.fixtures.fake_engines import FakeOcrEngine, MissingOcrEngine
from tests.fixtures.processing_samples import (
    make_pdf_blank,
    make_pdf_corrupt,
    make_pdf_encrypted,
    make_pdf_mixed,
    make_pdf_scanned,
    make_pdf_text,
)

NO_OCR = {"pdf_ocr_fallback": False}


def extract(data: bytes, extractor: PdfExtractor | None = None, **kwargs):
    extractor = extractor or PdfExtractor(MissingOcrEngine())
    return run(extractor, data, mime="application/pdf", **kwargs)


# --- text PDFs ------------------------------------------------------------------


def test_text_pdf_gives_block_segments_with_page_and_box():
    result = extract(make_pdf_text(3))
    assert result.outcome == "ok"
    pages = {s.locator.page for s in result.segments}
    assert pages == {1, 2, 3}
    assert all(s.segment_type == "pdf_text_block" for s in result.segments)
    assert_locators_valid(result)


def test_boxes_lie_inside_their_pages_and_pages_are_in_order():
    result = extract(make_pdf_text(3))
    page_numbers = [s.locator.page for s in result.segments]
    assert page_numbers == sorted(page_numbers)
    for segment in result.segments:
        x0, y0, x1, y1 = segment.locator.bbox
        assert 0 <= x0 < x1 <= segment.locator.page_width + 1
        assert 0 <= y0 < y1 <= segment.locator.page_height + 1
        assert segment.locator.page_width == 595 and segment.locator.page_height == 842


def test_text_is_extracted_verbatim():
    result = extract(make_pdf_text(1))
    joined = " ".join(s.text for s in result.segments)
    assert "Synthetic page 1 heading" in joined
    assert "SYNTHETIC TEST FIXTURE" in joined


def test_metadata_has_page_summary_and_counts():
    result = extract(make_pdf_text(2))
    assert result.metadata["page_count"] == 2
    summary = result.metadata["pages"]
    assert [p["page"] for p in summary] == [1, 2]
    assert all(p["has_text"] and not p["scanned"] for p in summary)
    assert result.metadata["ocr_pages"] == []


def test_page_limit_truncates_and_marks_partial():
    result = extract(make_pdf_text(4), limits=ExtractionLimits(max_pdf_pages=2))
    assert {s.locator.page for s in result.segments} == {1, 2}
    assert result.outcome == "partial"
    assert "page_limit_reached" in warning_codes(result)
    assert result.metadata["page_count"] == 4 and result.metadata["pages_extracted"] == 2


def test_character_limit_truncates_and_marks_partial():
    result = extract(make_pdf_text(3), limits=ExtractionLimits(max_extracted_chars=60))
    assert result.outcome == "partial"
    assert "char_limit_reached" in warning_codes(result)


# --- scanned, mixed and blank ---------------------------------------------------


def test_scanned_pdf_without_ocr_needs_ocr():
    result = extract(make_pdf_scanned(), options=NO_OCR)
    assert result.outcome == "needs_ocr"
    assert result.segments == []
    detail = next(w.detail for w in result.warnings if w.code == "pages_need_ocr")
    assert detail == {"pages": [1]}
    assert result.metadata["pages"][0]["scanned"] is True


def test_scanned_pdf_with_missing_ocr_engine_degrades_to_needs_ocr():
    result = extract(make_pdf_scanned(), PdfExtractor(MissingOcrEngine()))
    assert result.outcome == "needs_ocr"
    assert "ocr_unavailable" in warning_codes(result)
    assert "pages_need_ocr" in warning_codes(result)


def test_mixed_pdf_without_ocr_is_partial_and_names_the_pages():
    result = extract(make_pdf_mixed(), options=NO_OCR)
    assert result.outcome == "partial"
    assert {s.locator.page for s in result.segments} == {1}
    detail = next(w.detail for w in result.warnings if w.code == "pages_need_ocr")
    assert detail == {"pages": [2]}


def test_scanned_pdf_with_ocr_engine_yields_ocr_lines_in_pdf_points():
    result = extract(make_pdf_scanned(), PdfExtractor(FakeOcrEngine()))
    assert result.outcome == "ok"
    assert [s.segment_type for s in result.segments] == ["ocr_line"]
    line = result.segments[0]
    assert line.text == "SYNTHETIC PAGE"
    assert line.locator.page == 1
    x0, y0, x1, y1 = line.locator.bbox
    assert x1 <= 595 and y1 <= 842  # mapped from pixels back to PDF points
    assert x1 > 10 and line.data["source"] == "ocr"
    assert 0 < line.engine_confidence <= 1
    assert "ocr_applied" in warning_codes(result)
    assert result.metadata["ocr_pages"] == [1]
    assert result.metadata["pages"][0]["ocr_applied"] is True
    assert_locators_valid(result)


def test_ocr_runs_only_on_scanned_pages():
    engine = FakeOcrEngine()
    result = extract(make_pdf_mixed(), PdfExtractor(engine))
    assert engine.calls == 1
    pages = {s.segment_type: s.locator.page for s in result.segments}
    assert pages == {"pdf_text_block": 1, "ocr_line": 2}
    assert result.outcome == "ok"


def test_low_confidence_ocr_makes_the_result_partial():
    engine = FakeOcrEngine([("blurry", 12.0, 5, 5, 50, 20, 1, 1, 1)])
    result = extract(make_pdf_scanned(), PdfExtractor(engine))
    assert result.outcome == "partial"
    assert "low_confidence" in warning_codes(result)


def test_ocr_that_finds_no_text_leaves_the_page_unresolved():
    result = extract(make_pdf_scanned(), PdfExtractor(FakeOcrEngine([])))
    assert result.outcome == "needs_ocr"


def test_blank_pdf_is_empty():
    result = extract(make_pdf_blank())
    assert result.outcome == "empty"
    assert result.segments == []
    assert "no_text_found" in warning_codes(result)


# --- encryption and corruption --------------------------------------------------


def test_password_protected_pdf_fails_and_no_password_is_guessed():
    with pytest.raises(PasswordRequiredError):
        extract(make_pdf_encrypted(True))


def test_encrypted_pdf_that_opens_without_a_password_is_flagged():
    result = extract(make_pdf_encrypted(False))
    assert "encrypted_no_user_password" in warning_codes(result)
    assert any("protected page" in s.text for s in result.segments)


@pytest.mark.parametrize(
    "data",
    [b"", b"not a pdf at all", b"%PDF-1.4\n", make_pdf_corrupt(), b"%PDF-" + bytes(range(256)) * 4],
    ids=["empty", "text", "header-only", "truncated", "garbage"],
)
def test_unreadable_pdfs_fail_without_crashing(data):
    # A damaged PDF may be repaired (and warned about) or refused. It must never crash.
    try:
        result = extract(data)
    except CorruptFileError:
        return
    assert result.outcome in {"empty", "needs_ocr", "partial", "ok"}


def test_truncated_pdf_is_refused_or_repaired_with_a_warning():
    try:
        result = extract(make_pdf_corrupt())
    except CorruptFileError:
        return
    assert "pdf_repaired" in warning_codes(result) or result.outcome != "ok"


# --- real OCR engine (skipped when Tesseract is not installed) -------------------


@pytest.mark.skipif(find_tesseract() is None, reason="Tesseract is not installed")
def test_real_tesseract_reads_a_scanned_pdf_page():
    result = run(
        PdfExtractor(),
        make_pdf_scanned("SYNTHETIC SCANNED PAGE"),
        mime="application/pdf",
        options={"tesseract_langs": "eng", "pdf_ocr_fallback": True},
    )
    text = " ".join(s.text for s in result.segments).upper()
    assert "SYNTHETIC" in text and "SCANNED" in text
    assert all(s.segment_type == "ocr_line" and s.locator.page == 1 for s in result.segments)
