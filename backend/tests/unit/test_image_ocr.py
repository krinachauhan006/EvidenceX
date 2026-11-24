"""Image extractor: line grouping, metadata, limits and the Tesseract adapter."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.modules.processing.errors import (
    CorruptFileError,
    DependencyMissingError,
    LimitExceededError,
)
from app.modules.processing.extractors.image_ocr import ImageOcrExtractor
from app.modules.processing.extractors.ocr_engine import (
    TesseractEngine,
    find_tesseract,
    group_words_into_lines,
)
from app.modules.processing.limits import ExtractionLimits
from tests.fixtures.extraction import assert_locators_valid, run, warning_codes
from tests.fixtures.fake_engines import FakeOcrEngine, MissingOcrEngine, ocr_data
from tests.fixtures.processing_samples import (
    make_blank_png,
    make_corrupt_png,
    make_jpeg_with_exif,
    make_rotated_jpeg,
    make_text_png,
)

OPTIONS = {"tesseract_langs": "eng", "ocr_min_confidence": 0.4}


def extract(data: bytes, engine=None, **kwargs):
    kwargs.setdefault("options", OPTIONS)
    return run(ImageOcrExtractor(engine or FakeOcrEngine()), data, mime="image/png", **kwargs)


# --- group_words_into_lines (pure) ----------------------------------------------


def test_words_are_grouped_by_line_with_union_box_and_mean_confidence():
    data = ocr_data(
        [
            ("Hello", 90.0, 10, 10, 40, 20, 1, 1, 1),
            ("world", 80.0, 60, 12, 50, 18, 1, 1, 1),
            ("Second", 70.0, 10, 50, 60, 20, 1, 1, 2),
        ]
    )
    lines = group_words_into_lines(data, 300, 200)
    assert [line.text for line in lines] == ["Hello world", "Second"]
    assert lines[0].bbox == (10, 10, 110, 30)
    assert lines[0].confidence == pytest.approx(0.85)
    assert lines[0].words[1] == {"text": "world", "bbox": [60, 12, 110, 30], "confidence": 0.8}


def test_layout_markers_and_empty_words_are_dropped():
    data = ocr_data(
        [
            ("", -1, 0, 0, 300, 200, 1, 0, 0),
            ("   ", 95.0, 5, 5, 10, 10, 1, 1, 1),
            ("kept", 88.0, 5, 5, 40, 10, 1, 1, 1),
            ("lost", -1, 50, 5, 40, 10, 1, 1, 1),
        ]
    )
    lines = group_words_into_lines(data, 100, 100)
    assert [line.text for line in lines] == ["kept"]


def test_reading_order_is_preserved_and_boxes_are_clamped_to_the_image():
    data = ocr_data(
        [
            ("later", 90.0, 5, 80, 40, 30, 2, 1, 1),
            ("first", 90.0, 90, -5, 40, 30, 1, 1, 1),
        ]
    )
    lines = group_words_into_lines(data, 100, 100)
    assert [line.text for line in lines] == ["later", "first"]
    assert lines[0].bbox[3] == 100  # 80 + 30 clamped to the image height
    assert lines[1].bbox[0] == 90 and lines[1].bbox[1] == 0 and lines[1].bbox[2] == 100


def test_string_confidences_and_missing_values_are_tolerated():
    data = ocr_data([("ok", "91.5", 1, 1, 10, 10, 1, 1, 1), ("bad", "n/a", 1, 1, 10, 10, 1, 1, 2)])
    assert [line.text for line in group_words_into_lines(data, 50, 50)] == ["ok"]


def test_empty_data_gives_no_lines():
    assert group_words_into_lines({}, 10, 10) == []


# --- extraction with a fake engine ----------------------------------------------


def test_lines_become_ocr_segments_with_pixel_boxes_and_engine_confidence():
    result = extract(make_blank_png(200, 100))
    assert result.outcome == "ok"
    assert [s.text for s in result.segments] == ["SYNTHETIC PAGE"]
    segment = result.segments[0]
    assert segment.segment_type == "ocr_line"
    assert segment.locator.kind == "image"
    assert (segment.locator.width, segment.locator.height) == (200, 100)
    assert segment.locator.bbox == (10, 10, 170, 30)
    assert segment.engine_confidence == pytest.approx(0.94)
    assert segment.language == "eng"
    assert len(segment.data["words"]) == 2
    assert_locators_valid(result)


def test_metadata_records_image_and_engine_details():
    meta = extract(make_blank_png(200, 100)).metadata
    assert (meta["width"], meta["height"], meta["format"]) == (200, 100, "PNG")
    assert meta["ocr_engine"] == "fake-ocr" and meta["ocr_language"] == "eng"
    assert meta["word_count"] == 2 and meta["line_count"] == 1
    assert meta["mean_engine_confidence"] == pytest.approx(0.94)


def test_no_text_is_empty_with_a_warning():
    result = extract(make_blank_png(), FakeOcrEngine([]))
    assert result.outcome == "empty" and result.segments == []
    assert "no_text_detected" in warning_codes(result)


def test_low_confidence_keeps_the_text_but_is_partial():
    engine = FakeOcrEngine([("smudged", 20.0, 5, 5, 60, 20, 1, 1, 1)])
    result = extract(make_blank_png(), engine)
    assert result.outcome == "partial"
    assert [s.text for s in result.segments] == ["smudged"]
    assert "low_confidence" in warning_codes(result)


def test_exif_orientation_is_applied_to_the_image_and_the_locator():
    result = extract(make_rotated_jpeg())
    segment = result.segments[0]
    assert (segment.locator.width, segment.locator.height) == (60, 120)  # 120x60 rotated
    assert result.metadata["exif_orientation_applied"] is True


def test_exif_fields_are_kept_as_written_without_conversion():
    exif = extract(make_jpeg_with_exif()).metadata["exif"]
    assert exif["make"] == "Synthetic Camera Co"
    assert exif["model"] == "Model T-1"
    assert exif["datetime"] == "2026:10:12 09:30:00"  # raw string, no timezone invented
    assert exif["has_gps"] is False


def test_transparent_png_is_flattened_onto_white_for_ocr():
    buf = io.BytesIO()
    Image.new("RGBA", (50, 50), (0, 0, 0, 0)).save(buf, "PNG")
    assert extract(buf.getvalue()).outcome == "ok"


# --- failures -------------------------------------------------------------------


@pytest.mark.parametrize(
    "data", [b"", b"not an image", make_corrupt_png()], ids=["empty", "text", "bad-png"]
)
def test_undecodable_images_fail_as_corrupt(data):
    with pytest.raises(CorruptFileError):
        extract(data)


def test_pixel_limit_fails_before_decoding_the_image():
    with pytest.raises(LimitExceededError):
        extract(make_blank_png(400, 300), limits=ExtractionLimits(max_image_pixels=10_000))


def test_missing_ocr_engine_fails_with_a_clear_dependency_error():
    with pytest.raises(DependencyMissingError, match="TESSERACT_CMD"):
        extract(make_blank_png(), MissingOcrEngine())


def test_tesseract_adapter_reports_a_missing_binary(tmp_path):
    engine = TesseractEngine()
    with pytest.raises(DependencyMissingError, match="TESSERACT_CMD"):
        engine.version({"tesseract_cmd": str(tmp_path / "does-not-exist.exe")})


def test_find_tesseract_prefers_the_configured_path(tmp_path):
    fake = tmp_path / "tesseract.exe"
    fake.write_bytes(b"")
    assert find_tesseract(str(fake)) == str(fake)
    assert find_tesseract(str(tmp_path / "missing.exe")) is None


def test_instruction_like_text_in_an_image_is_stored_as_data():
    words = [
        ("IGNORE", 90.0, 1, 1, 50, 10, 1, 1, 1),
        ("INSTRUCTIONS", 90.0, 60, 1, 90, 10, 1, 1, 1),
    ]
    engine = FakeOcrEngine(words)
    assert extract(make_blank_png(), engine).segments[0].text == "IGNORE INSTRUCTIONS"


# --- real engine (skipped when Tesseract is not installed) -----------------------


@pytest.mark.skipif(find_tesseract() is None, reason="Tesseract is not installed")
def test_real_tesseract_reads_generated_text():
    result = run(
        ImageOcrExtractor(),
        make_text_png("SYNTHETIC SAMPLE INVOICE 4821"),
        mime="image/png",
        options=OPTIONS,
    )
    text = " ".join(s.text for s in result.segments).upper()
    assert "SYNTHETIC" in text and "INVOICE" in text
    assert result.outcome in {"ok", "partial"}
    assert result.extractor_version.startswith("tesseract")


@pytest.mark.skipif(find_tesseract() is None, reason="Tesseract is not installed")
def test_real_tesseract_finds_nothing_in_a_blank_image():
    result = run(ImageOcrExtractor(), make_blank_png(), mime="image/png", options=OPTIONS)
    assert result.outcome == "empty"
