"""Image extractor: metadata and OCR text lines (Pillow + an OCR engine).

Pixel boxes are relative to the image AFTER the EXIF orientation is applied, which is
how browsers display it. Table structure is not reconstructed; text comes back as
lines with positions. OCR output is engine-read text, not verified text.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from typing import Any

from app.modules.processing.errors import (
    CorruptFileError,
    DependencyMissingError,
    ExtractionError,
    LimitExceededError,
)
from app.modules.processing.extractors.base import (
    ExtractionInput,
    ExtractionResult,
    ExtractionWarning,
    SegmentDraft,
)
from app.modules.processing.extractors.ocr_engine import (
    OcrEngine,
    TesseractEngine,
    group_words_into_lines,
)
from app.modules.processing.locators import ImageLocator

# Tags worth showing. Values are kept exactly as written; nothing is converted.
_EXIF_TAGS = {
    271: "make",
    272: "model",
    305: "software",
    306: "datetime",
    274: "orientation",
    315: "artist",
    33432: "copyright",
}
_EXIF_IFD_TAGS = {36867: "datetime_original", 36868: "datetime_digitized"}
_GPS_IFD = 0x8825
_EXIF_IFD = 0x8769
_MAX_EXIF_CHARS = 200


def _clean(value: Any) -> Any:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value.replace("\x00", "").strip()[:_MAX_EXIF_CHARS]
    if isinstance(value, (int, float)):
        return value
    return None


def read_exif(image: Any) -> dict[str, Any]:
    """A small allow-list of EXIF fields, as raw values."""
    out: dict[str, Any] = {}
    try:
        exif = image.getexif()
        for tag, name in _EXIF_TAGS.items():
            value = _clean(exif.get(tag))
            if value not in (None, ""):
                out[name] = value
        ifd = exif.get_ifd(_EXIF_IFD)
        for tag, name in _EXIF_IFD_TAGS.items():
            value = _clean(ifd.get(tag))
            if value not in (None, ""):
                out[name] = value
        out["has_gps"] = bool(exif.get_ifd(_GPS_IFD))
    except Exception:  # noqa: BLE001 - metadata is supplementary
        return {}
    return out


def open_image(data: bytes, max_pixels: int) -> Any:
    """Open and fully decode an image with a pixel-count guard. Returns a Pillow image
    with EXIF orientation applied and a colour mode OCR can read."""
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise DependencyMissingError(
            "Pillow is not installed. Install it with: pip install pillow"
        ) from exc
    try:
        image = Image.open(io.BytesIO(data))
        width, height = image.size
        if width * height > max_pixels:
            raise LimitExceededError(f"The image is larger than {max_pixels:,} pixels.")
        image.load()
    except ExtractionError:
        raise
    except Image.DecompressionBombError as exc:
        raise LimitExceededError(f"The image is larger than {max_pixels:,} pixels.") from exc
    except Exception as exc:  # noqa: BLE001 - any decode problem means a bad image
        raise CorruptFileError("The image could not be decoded.") from exc

    exif = read_exif(image)
    fmt = image.format
    oriented = ImageOps.exif_transpose(image)
    if oriented.mode in ("RGBA", "LA", "P"):
        rgba = oriented.convert("RGBA")
        flat = Image.new("RGB", rgba.size, "white")
        flat.paste(rgba, mask=rgba.getchannel("A"))
        oriented = flat
    elif oriented.mode != "RGB":
        oriented = oriented.convert("RGB")
    oriented.info["_evidencex_format"] = fmt
    oriented.info["_evidencex_exif"] = exif
    return oriented


def ocr_lines_for_image(
    engine: OcrEngine, image: Any, options: Mapping[str, Any]
) -> tuple[list, float | None]:
    """Run OCR and group words. Returns (lines, mean word confidence or None).

    With ``ocr_preprocess`` the engine reads a contrast-enhanced, orientation- and
    skew-corrected copy; boxes are mapped back to the original image coordinates.
    """
    width, height = image.size
    steps: list[str] = []
    if options.get("ocr_preprocess"):
        from app.modules.processing.extractors.ocr_preprocess import map_data_back, prepare

        processed, ctx = prepare(image, options)
        raw = map_data_back(engine.recognize(processed, options), ctx)
        steps = ctx["steps"]
    else:
        raw = engine.recognize(image, options)
    if isinstance(options, dict):
        options.setdefault("_ocr_steps", steps)  # read back by the extractor (metadata)
    lines = group_words_into_lines(raw, width, height)
    words = [w["confidence"] for line in lines for w in line.words]
    mean = sum(words) / len(words) if words else None
    return lines, mean


class ImageOcrExtractor:
    name = "image_ocr"
    version = "1"

    def __init__(self, engine: OcrEngine | None = None) -> None:
        self._engine: OcrEngine = engine or TesseractEngine()

    def extract(self, inp: ExtractionInput) -> ExtractionResult:
        options = inp.options
        image = open_image(inp.data, inp.limits.max_image_pixels)
        width, height = image.size
        exif = image.info.get("_evidencex_exif", {})
        fmt = image.info.get("_evidencex_format")

        engine_version = self._engine.version(options)
        lines, mean = ocr_lines_for_image(self._engine, image, options)

        segments = [
            SegmentDraft(
                segment_type="ocr_line",
                text=line.text,
                locator=ImageLocator(bbox=line.bbox, width=width, height=height),
                data={"words": line.words},
                engine_confidence=line.confidence,
                language=str(options.get("tesseract_langs") or "eng"),
            )
            for line in lines
        ]

        warnings: list[ExtractionWarning] = []
        min_conf = float(options.get("ocr_min_confidence", 0.4))
        if not segments:
            outcome = "empty"
            warnings.append(
                ExtractionWarning("no_text_detected", "OCR did not detect any text in the image.")
            )
        elif mean is not None and mean < min_conf:
            outcome = "partial"
            warnings.append(
                ExtractionWarning(
                    "low_confidence",
                    "The OCR engine reported low confidence. The text is kept but may "
                    "contain misreadings.",
                    {"mean_engine_confidence": round(mean, 4), "threshold": min_conf},
                )
            )
        else:
            outcome = "ok"
        if exif.get("has_gps"):
            warnings.append(
                ExtractionWarning(
                    "gps_metadata_present",
                    "The image carries GPS location metadata. Coordinates are not extracted.",
                )
            )

        metadata = {
            "width": width,
            "height": height,
            "format": fmt,
            "ocr_engine": self._engine.name,
            "ocr_engine_version": engine_version,
            "ocr_language": str(options.get("tesseract_langs") or "eng"),
            "line_count": len(segments),
            "word_count": sum(len(line.words) for line in lines),
            "mean_engine_confidence": mean,
            "exif": exif,
            "exif_orientation_applied": True,
            "text_source": "ocr",  # never digitally embedded text
            "ocr_preprocessing": list(options.get("_ocr_steps") or [])
            if isinstance(options, dict)
            else [],
            "low_confidence_lines": sum(
                1 for s in segments if (s.engine_confidence or 0) < min_conf
            ),
        }
        return ExtractionResult(self.name, engine_version, outcome, segments, metadata, warnings)
