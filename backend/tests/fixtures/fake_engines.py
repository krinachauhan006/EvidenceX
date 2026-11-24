"""Fake OCR and speech engines. They stand in for Tesseract and Whisper in unit tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.modules.processing.errors import DependencyMissingError
from app.modules.processing.extractors.audio import Transcription, TranscriptSegment


def ocr_data(words: list[tuple]) -> dict[str, list]:
    """Build the dictionary ``pytesseract.image_to_data`` returns.

    Each word is (text, conf, left, top, width, height, block, par, line).
    """
    keys = ["text", "conf", "left", "top", "width", "height", "block_num", "par_num", "line_num"]
    data: dict[str, list] = {k: [] for k in keys}
    data["level"], data["page_num"], data["word_num"] = [], [], []
    for index, word in enumerate(words, 1):
        for key, value in zip(keys, word, strict=True):
            data[key].append(value)
        data["level"].append(5)
        data["page_num"].append(1)
        data["word_num"].append(index)
    return data


class FakeOcrEngine:
    name = "fake-ocr"

    def __init__(self, words: list[tuple] | None = None) -> None:
        self.words = words if words is not None else [
            ("SYNTHETIC", 96.0, 10, 10, 100, 20, 1, 1, 1),
            ("PAGE", 92.0, 120, 10, 50, 20, 1, 1, 1),
        ]
        self.calls = 0

    def version(self, options: Mapping[str, Any]) -> str:
        return "fake-ocr 1.0"

    def recognize(self, image: Any, options: Mapping[str, Any]) -> dict[str, list]:
        self.calls += 1
        return ocr_data(self.words)


class MissingOcrEngine:
    """Behaves like Tesseract that is not installed."""

    name = "missing-ocr"

    def version(self, options: Mapping[str, Any]) -> str:
        raise DependencyMissingError("Tesseract OCR was not found. Set TESSERACT_CMD.")

    def recognize(self, image: Any, options: Mapping[str, Any]) -> dict[str, list]:
        raise DependencyMissingError("Tesseract OCR was not found. Set TESSERACT_CMD.")


class FakeTranscriber:
    def __init__(self, segments: list[TranscriptSegment] | None = None, **kwargs: Any) -> None:
        self.segments = (
            segments
            if segments is not None
            else [
                TranscriptSegment(0.0, 2.4, " Synthetic first sentence. ", -0.2, 0.01, 1.1),
                TranscriptSegment(2.4, 5.0, "Synthetic second sentence.", -1.5, 0.05, 1.3),
            ]
        )
        self.kwargs = kwargs
        self.calls = 0

    def transcribe(self, data: bytes, options: Mapping[str, Any]) -> Transcription:
        self.calls += 1
        return Transcription(
            segments=self.segments,
            duration=5.0,
            language="en",
            language_probability=0.98,
            model="fake",
            device="cpu",
            compute_type="int8",
            engine="fake-whisper",
            engine_version="fake 1.0",
        )
