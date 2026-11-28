"""OCR engine seam: line grouping (pure) and the Tesseract adapter.

``group_words_into_lines`` is a pure function of the dictionary that
``pytesseract.image_to_data`` returns, so it is tested without Tesseract installed.
Engine confidence is the engine's own score. It says nothing about factual accuracy.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.modules.processing.errors import (
    DependencyMissingError,
    ExtractionInterruptedError,
    ExtractionTimeoutError,
    UnsupportedContentError,
)

DEFAULT_WINDOWS_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Exit statuses of a tesseract process that was stopped from outside rather than one
# that rejected the image: Windows STATUS_CONTROL_C_EXIT (0xC000013A, as reported
# unsigned and signed; also used when the console closes) and, on POSIX, death by
# SIGINT or SIGTERM. Ctrl+C in a console reaches every process attached to it,
# including the tesseract child of an inline OCR run.
INTERRUPTED_EXIT_STATUSES = frozenset({0xC000013A, 0xC000013A - (1 << 32), -2, -15})


def is_interrupted_status(status: Any) -> bool:
    return isinstance(status, int) and status in INTERRUPTED_EXIT_STATUSES


@dataclass
class OcrLine:
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float  # 0..1, mean of the word confidences
    words: list[dict[str, Any]] = field(default_factory=list)


class OcrEngine(Protocol):
    name: str

    def version(self, options: Mapping[str, Any]) -> str: ...

    def recognize(self, image: Any, options: Mapping[str, Any]) -> Mapping[str, list]: ...


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def group_words_into_lines(data: Mapping[str, list], width: int, height: int) -> list[OcrLine]:
    """Group Tesseract word records into lines, keeping reading order.

    Words with confidence -1 (layout markers) and empty text are dropped. The line
    box is the union of its word boxes, clamped to the image.
    """
    texts = data.get("text") or []
    groups: dict[tuple[Any, Any, Any], list[dict[str, Any]]] = {}
    for i, raw_text in enumerate(texts):
        text = (raw_text or "").strip()
        conf = _number(data["conf"][i])
        if not text or conf is None or conf < 0:
            continue
        left, top = _number(data["left"][i]), _number(data["top"][i])
        w, h = _number(data["width"][i]), _number(data["height"][i])
        if None in (left, top, w, h):
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        groups.setdefault(key, []).append(
            {
                "text": text,
                "bbox": [left, top, left + w, top + h],
                "confidence": max(0.0, min(1.0, conf / 100)),
            }
        )

    lines: list[OcrLine] = []
    for words in groups.values():
        x0 = max(0.0, min(w["bbox"][0] for w in words))
        y0 = max(0.0, min(w["bbox"][1] for w in words))
        x1 = min(float(width), max(w["bbox"][2] for w in words))
        y1 = min(float(height), max(w["bbox"][3] for w in words))
        if x1 < x0 or y1 < y0:
            continue
        mean = sum(w["confidence"] for w in words) / len(words)
        lines.append(OcrLine(" ".join(w["text"] for w in words), (x0, y0, x1, y1), mean, words))
    return lines


def find_tesseract(configured: str = "") -> str | None:
    """The configured path, else PATH, else the default Windows install folder."""
    if configured:
        return configured if os.path.isfile(configured) else None
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    return DEFAULT_WINDOWS_TESSERACT if os.path.isfile(DEFAULT_WINDOWS_TESSERACT) else None


_MISSING_MESSAGE = (
    "Tesseract OCR was not found. Install it and set TESSERACT_CMD to the full path of "
    "tesseract.exe."
)


class TesseractEngine:
    name = "tesseract"

    def _module(self, options: Mapping[str, Any]) -> Any:
        try:
            import pytesseract
        except ImportError as exc:
            raise DependencyMissingError(
                "pytesseract is not installed. Install it with: pip install pytesseract"
            ) from exc
        path = find_tesseract(str(options.get("tesseract_cmd") or ""))
        if path is None:
            raise DependencyMissingError(_MISSING_MESSAGE)
        pytesseract.pytesseract.tesseract_cmd = path
        return pytesseract

    def version(self, options: Mapping[str, Any]) -> str:
        module = self._module(options)
        try:
            return f"tesseract {module.get_tesseract_version()}"
        except Exception as exc:  # noqa: BLE001
            raise DependencyMissingError(_MISSING_MESSAGE) from exc

    def recognize(self, image: Any, options: Mapping[str, Any]) -> Mapping[str, list]:
        module = self._module(options)
        langs = str(options.get("tesseract_langs") or "eng")
        timeout = int(options.get("ocr_timeout_seconds") or 120)
        try:
            return module.image_to_data(
                image, lang=langs, output_type=module.Output.DICT, timeout=timeout
            )
        except module.TesseractNotFoundError as exc:
            raise DependencyMissingError(_MISSING_MESSAGE) from exc
        # TesseractError is a RuntimeError subclass, so it must be handled first.
        except module.TesseractError as exc:
            if is_interrupted_status(getattr(exc, "status", None)):
                raise ExtractionInterruptedError(
                    "OCR was interrupted before it finished (for example by Ctrl+C). "
                    "The file was not judged; process it again."
                ) from exc
            if "load" in str(exc).lower() and "lang" in str(exc).lower():
                raise DependencyMissingError(
                    f"Tesseract language data for '{langs}' is missing. Install it or "
                    "change TESSERACT_LANGS."
                ) from exc
            raise UnsupportedContentError("OCR could not process this image.") from exc
        except RuntimeError as exc:  # pytesseract raises RuntimeError on timeout
            if "timeout" in str(exc).lower():
                raise ExtractionTimeoutError("OCR took too long and was stopped.") from exc
            raise
