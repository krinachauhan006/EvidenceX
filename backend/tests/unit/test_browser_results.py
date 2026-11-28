"""Unit tests for the browser result checks and builders (browser_results.py) and the
server-side file facts used to verify them (browser_service.py)."""

from __future__ import annotations

import io
import math

import pytest
from PIL import Image

from app.core.config import Settings
from app.modules.processing.browser_results import (
    BrowserResultError,
    ServerFacts,
    build_audio_result,
    build_image_result,
    check_bbox,
    check_span,
    clean_text,
)
from app.modules.processing.browser_schemas import (
    BrowserAudioResultIn,
    BrowserEngineIn,
    BrowserImageResultIn,
)
from app.modules.processing.browser_service import _image_size, browser_processable

ENGINE = BrowserEngineIn(ocr_engine_version="7.0.0", speech_engine_version="4.3.2")


def image(lines, width=100, height=50) -> BrowserImageResultIn:
    return BrowserImageResultIn.model_validate(
        {"kind": "image", "width": width, "height": height, "language": "eng", "lines": lines}
    )


def test_clean_text_removes_control_characters_only():
    assert clean_text("  A\x00B\x07 C\tD\n ") == "AB C\tD"


def test_bbox_small_overshoot_is_clamped_larger_is_refused():
    assert check_bbox([-1.5, 0, 101.9, 50], 100, 50) == (0.0, 0.0, 100.0, 50.0)
    with pytest.raises(BrowserResultError, match="outside"):
        check_bbox([0, 0, 103, 10], 100, 50)
    with pytest.raises(BrowserResultError, match="wrong order"):
        check_bbox([10, 0, 5, 10], 100, 50)
    with pytest.raises(BrowserResultError, match="finite"):
        check_bbox([math.inf, 0, 5, 10], 100, 50)


def test_span_is_clamped_to_the_recording_within_tolerance():
    assert check_span(1.0, 2.4, 2.0) == (1.0, 2.0, True)
    assert check_span(0.0, 1.0, 2.0) == (0.0, 1.0, False)
    with pytest.raises(BrowserResultError, match="ends before"):
        check_span(2.0, 1.0, 5.0)
    with pytest.raises(BrowserResultError, match="beyond the end"):
        check_span(0.0, 3.5, 2.0)


def test_image_lines_mirror_the_server_grouping():
    result = build_image_result(
        image(
            [
                {
                    "text": " Hello world ",
                    "bbox": [1, 1, 60, 10],
                    "confidence": 0.99,  # ignored: recomputed from the words
                    "words": [
                        {"text": "Hello", "bbox": [1, 1, 30, 10], "confidence": 0.5},
                        {"text": " ", "bbox": [30, 1, 31, 10], "confidence": 0.1},
                        {"text": "world", "bbox": [32, 1, 60, 10], "confidence": 0.7},
                    ],
                },
                {"text": "\x00 ", "bbox": [1, 20, 5, 30]},  # nothing left: dropped
            ]
        ),
        ENGINE,
        ServerFacts(image_size=(100, 50)),
        min_confidence=0.4,
        max_chars=1000,
    )
    (seg,) = result.segments
    assert seg.text == "Hello world" and seg.segment_type == "ocr_line"
    assert seg.engine_confidence == pytest.approx(0.6)
    assert [w["text"] for w in seg.data["words"]] == ["Hello", "world"]
    assert result.outcome == "ok" and result.metadata["word_count"] == 2


def test_low_mean_confidence_is_partial_never_ok():
    lines = [
        {
            "text": "faint",
            "bbox": [0, 0, 10, 10],
            "words": [{"text": "faint", "bbox": [0, 0, 10, 10], "confidence": 0.2}],
        }
    ]
    result = build_image_result(
        image(lines), ENGINE, ServerFacts(), min_confidence=0.4, max_chars=1000
    )
    assert result.outcome == "partial"
    assert "low_confidence" in [w.code for w in result.warnings]
    assert result.metadata["size_verified_by_server"] is False


def test_image_text_over_the_limit_is_refused():
    lines = [{"text": "x" * 50, "bbox": [0, 0, 10, 10]}]
    with pytest.raises(BrowserResultError, match="more text"):
        build_image_result(image(lines), ENGINE, ServerFacts(), min_confidence=0.4, max_chars=10)


def test_audio_over_the_limit_is_cut_at_a_segment_and_partial():
    payload = BrowserAudioResultIn.model_validate(
        {
            "kind": "audio",
            "duration_seconds": 10,
            "segments": [
                {"start": 0, "end": 2, "text": "first part"},
                {"start": 2, "end": 4, "text": "second part"},
            ],
        }
    )
    result = build_audio_result(payload, ENGINE, ServerFacts(), max_audio_seconds=100, max_chars=15)
    assert [s.text for s in result.segments] == ["first part"]
    assert result.outcome == "partial"
    assert "char_limit_reached" in [w.code for w in result.warnings]
    assert all(s.engine_confidence is None for s in result.segments)


def test_audio_longer_than_the_server_limit_is_refused():
    payload = BrowserAudioResultIn.model_validate(
        {"kind": "audio", "duration_seconds": 500, "segments": []}
    )
    with pytest.raises(BrowserResultError, match="longer than"):
        build_audio_result(payload, ENGINE, ServerFacts(), max_audio_seconds=100, max_chars=10)


def test_server_image_size_applies_the_exif_rotation():
    buf = io.BytesIO()
    exif = Image.Exif()
    exif[274] = 6  # rotate 90 degrees: displayed as 50 x 100
    Image.new("RGB", (100, 50)).save(buf, format="JPEG", exif=exif)
    assert _image_size(buf.getvalue(), 50_000_000) == (50, 100)
    with pytest.raises(BrowserResultError, match="larger than"):
        _image_size(buf.getvalue(), 100)
    with pytest.raises(BrowserResultError, match="could not read"):
        _image_size(b"\x89PNG\r\n\x1a\nnot an image", 50_000_000)


def test_browser_processing_is_offered_only_for_worker_types():
    s = Settings(EXTERNAL_WORKER_MIMES="image/png,audio/wav,text/csv")
    assert browser_processable("image/png", s) and browser_processable("audio/wav", s)
    assert not browser_processable("image/jpeg", s)  # the server processes it itself
    assert not browser_processable("text/csv", s)  # never a browser type
    assert not browser_processable(
        "image/png", Settings(EXTERNAL_WORKER_MIMES="image/png", BROWSER_PROCESSING="false")
    )
