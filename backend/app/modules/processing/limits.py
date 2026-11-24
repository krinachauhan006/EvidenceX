"""Extraction safety limits, built from application settings."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.core.zip_safety import MB, ZipLimits


@dataclass(frozen=True)
class ExtractionLimits:
    max_pdf_pages: int = 500
    max_tabular_rows: int = 50_000
    max_cell_chars: int = 32_768
    max_extracted_chars: int = 5_000_000
    max_image_pixels: int = 50_000_000
    # XLSX package limits. The same values are used at upload and during extraction.
    max_zip_entries: int = 2_000
    max_zip_uncompressed_mb: int = 100
    max_zip_entry_mb: int = 50
    max_shared_strings_mb: int = 20
    max_zip_compression_ratio: int = 100

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> ExtractionLimits:
        s = settings or get_settings()
        return cls(
            max_pdf_pages=s.max_pdf_pages,
            max_tabular_rows=s.max_tabular_rows,
            max_cell_chars=s.max_cell_chars,
            max_extracted_chars=s.max_extracted_chars,
            max_image_pixels=s.max_image_pixels,
            max_zip_entries=s.max_zip_entries,
            max_zip_uncompressed_mb=s.max_zip_uncompressed_mb,
            max_zip_entry_mb=s.max_zip_entry_mb,
            max_shared_strings_mb=s.max_shared_strings_mb,
            max_zip_compression_ratio=s.max_zip_compression_ratio,
        )

    def zip_limits(self) -> ZipLimits:
        return ZipLimits(
            max_entries=self.max_zip_entries,
            max_total_uncompressed=self.max_zip_uncompressed_mb * MB,
            max_entry_uncompressed=self.max_zip_entry_mb * MB,
            max_shared_strings=self.max_shared_strings_mb * MB,
            max_ratio=self.max_zip_compression_ratio,
        )
