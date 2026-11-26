"""Maps a validated MIME type to its extractor.

The MIME type is the server-resolved value stored at upload time, never a
client-supplied one. Tests replace the registry through the ``get_registry``
dependency to inject fake extractors.

Every supported upload extension has an extractor here. A format without one would be
accepted at upload but could never be processed, so the two lists are kept in step
(and a test enforces it).
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.modules.processing.extractors.audio import AudioExtractor
from app.modules.processing.extractors.base import Extractor
from app.modules.processing.extractors.csv_extractor import CsvExtractor
from app.modules.processing.extractors.eml import EmlExtractor
from app.modules.processing.extractors.image_ocr import ImageOcrExtractor
from app.modules.processing.extractors.pdf import PdfExtractor
from app.modules.processing.extractors.video import VideoExtractor
from app.modules.processing.extractors.xlsx import XlsxExtractor

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
IMAGE_MIMES = ("image/png", "image/jpeg", "image/webp")
AUDIO_MIMES = ("audio/wav", "audio/mpeg", "audio/mp4")
VIDEO_MIMES = ("video/mp4", "video/quicktime", "video/webm")


class ExtractorRegistry:
    def __init__(self) -> None:
        self._by_mime: dict[str, Extractor] = {}

    def register(self, mime_type: str, extractor: Extractor) -> None:
        self._by_mime[mime_type] = extractor

    def unregister(self, mime_type: str) -> None:
        self._by_mime.pop(mime_type, None)

    def get(self, mime_type: str) -> Extractor | None:
        return self._by_mime.get(mime_type)

    def supports(self, mime_type: str) -> bool:
        return mime_type in self._by_mime

    def mime_types(self) -> list[str]:
        return sorted(self._by_mime)


def build_default_registry(settings: Settings | None = None) -> ExtractorRegistry:
    settings = settings or get_settings()
    registry = ExtractorRegistry()
    registry.register("text/csv", CsvExtractor())
    registry.register(XLSX_MIME, XlsxExtractor())
    registry.register("message/rfc822", EmlExtractor())

    image = ImageOcrExtractor()
    for mime in IMAGE_MIMES:
        registry.register(mime, image)

    audio = AudioExtractor()
    for mime in AUDIO_MIMES:
        registry.register(mime, audio)

    # PyMuPDF is AGPL-3.0 or commercial. PDF_EXTRACTION_ENABLED=false leaves it off.
    if settings.pdf_extraction_enabled:
        registry.register("application/pdf", PdfExtractor())

    video = VideoExtractor(audio=audio)
    for mime in VIDEO_MIMES:
        registry.register(mime, video)
    return registry


@lru_cache
def get_registry() -> ExtractorRegistry:
    return build_default_registry()
