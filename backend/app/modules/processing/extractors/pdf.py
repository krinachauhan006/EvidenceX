"""PDF extractor (PyMuPDF).

LICENSE NOTE: PyMuPDF is dual-licensed AGPL-3.0 or a commercial Artifex license. It is
used here unmodified, as a local library. If EvidenceX is ever offered to others as a
network service, the AGPL terms (or a commercial license) must be addressed first.
``PDF_EXTRACTION_ENABLED=false`` leaves PDF processing off.

Safety: the PDF is opened from memory. JavaScript is not run, links and embedded files
are not followed or opened (embedded file NAMES are listed in metadata), and nothing is
written to disk. Hostile PDFs are parsed by native code, which is why extraction sits
behind the ``ExtractionExecutor`` seam.

Scanned pages (no text layer, at least one image) are rendered and OCR'd when an OCR
engine is available and ``PDF_OCR_FALLBACK`` is on. OCR lines carry the PDF page and a
box in PDF points, mapped back from the rendered pixels.
"""

from __future__ import annotations

from typing import Any

from app.modules.processing.errors import (
    CorruptFileError,
    DependencyMissingError,
    ExtractionError,
    PasswordRequiredError,
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
from app.modules.processing.locators import PdfLocator

SCANNED_MIN_CHARS = 10
OCR_DPI = 200
_MAX_META_CHARS = 500


def _import_pymupdf() -> Any:
    try:
        import pymupdf

        return pymupdf
    except ImportError:
        try:
            import fitz

            return fitz
        except ImportError as exc:
            raise DependencyMissingError(
                "PyMuPDF is not installed. Install it with: pip install pymupdf"
            ) from exc


def _positive(value: float) -> float | None:
    return float(value) if value and value > 0 else None


class PdfExtractor:
    name = "pymupdf"
    version = "1"

    def __init__(self, ocr_engine: OcrEngine | None = None) -> None:
        self._ocr: OcrEngine = ocr_engine or TesseractEngine()

    def extract(self, inp: ExtractionInput) -> ExtractionResult:
        pymupdf = _import_pymupdf()
        limits = inp.limits
        try:
            doc = pymupdf.open(stream=inp.data, filetype="pdf")
        except Exception as exc:  # noqa: BLE001
            raise CorruptFileError("The PDF could not be opened.") from exc
        try:
            return self._extract(pymupdf, doc, inp, limits)
        except ExtractionError:
            raise
        except Exception as exc:  # noqa: BLE001 - parser failures mean an unreadable file
            raise CorruptFileError("The PDF could not be read.") from exc
        finally:
            doc.close()

    def _extract(
        self, pymupdf: Any, doc: Any, inp: ExtractionInput, limits: Any
    ) -> ExtractionResult:
        warnings: list[ExtractionWarning] = []
        if getattr(doc, "needs_pass", False):
            raise PasswordRequiredError("The PDF is password-protected.")
        # After an empty password authenticates, is_encrypted reads False, but the
        # metadata still names the encryption scheme.
        if getattr(doc, "is_encrypted", False) or (doc.metadata or {}).get("encryption"):
            warnings.append(
                ExtractionWarning(
                    "encrypted_no_user_password",
                    "The PDF is marked encrypted but opens without a password.",
                )
            )
        if getattr(doc, "is_repaired", False):
            warnings.append(
                ExtractionWarning(
                    "pdf_repaired", "The PDF structure was damaged and had to be repaired."
                )
            )

        total_pages = doc.page_count
        page_count = min(total_pages, limits.max_pdf_pages)
        segments: list[SegmentDraft] = []
        page_summaries: list[dict[str, Any]] = []
        scanned_pages: list[int] = []
        total_chars = 0
        truncated = False

        for index in range(page_count):
            page = doc[index]
            number = index + 1
            rect = page.rect
            width, height = _positive(rect.width), _positive(rect.height)
            page_chars = 0
            if not truncated:
                for block in page.get_text("blocks", sort=True):
                    if len(block) < 7 or block[6] != 0:
                        continue
                    text = (block[4] or "").strip()
                    if not text:
                        continue
                    if total_chars + len(text) > limits.max_extracted_chars:
                        truncated = True
                        break
                    total_chars += len(text)
                    page_chars += sum(1 for ch in text if not ch.isspace())
                    box = tuple(float(v) for v in block[:4])
                    segments.append(
                        SegmentDraft(
                            segment_type="pdf_text_block",
                            text=text,
                            locator=PdfLocator(
                                page=number,
                                bbox=box,  # type: ignore[arg-type]
                                page_width=width,
                                page_height=height,
                            ),
                        )
                    )
            try:
                image_count = len(page.get_images(full=False))
            except Exception:  # noqa: BLE001
                image_count = 0
            scanned = page_chars < SCANNED_MIN_CHARS and image_count >= 1
            if scanned:
                scanned_pages.append(number)
            page_summaries.append(
                {
                    "page": number,
                    "width": width,
                    "height": height,
                    "characters": page_chars,
                    "images": image_count,
                    "has_text": page_chars > 0,
                    "scanned": scanned,
                    "ocr_applied": False,
                }
            )

        ocr_pages, unresolved, ocr_confidences = self._ocr_scanned_pages(
            doc, inp, scanned_pages, page_summaries, segments, warnings
        )

        if total_pages > page_count:
            warnings.append(
                ExtractionWarning(
                    "page_limit_reached",
                    f"Only the first {page_count} of {total_pages} pages were extracted.",
                    {"limit": limits.max_pdf_pages, "pages": total_pages},
                )
            )
        if truncated:
            warnings.append(
                ExtractionWarning(
                    "char_limit_reached",
                    "Extraction stopped because the total text limit was reached.",
                    {"limit": limits.max_extracted_chars},
                )
            )
        if ocr_pages:
            warnings.append(
                ExtractionWarning(
                    "ocr_applied",
                    "These pages had no text layer. Their text was read by OCR and may "
                    "contain misreadings.",
                    {"pages": ocr_pages},
                )
            )
        if unresolved:
            warnings.append(
                ExtractionWarning(
                    "pages_need_ocr",
                    "These pages have no text layer and no text could be read from them.",
                    {"pages": unresolved},
                )
            )

        min_conf = float(inp.options.get("ocr_min_confidence", 0.4))
        mean_conf = sum(ocr_confidences) / len(ocr_confidences) if ocr_confidences else None
        low_conf = mean_conf is not None and mean_conf < min_conf
        if low_conf:
            warnings.append(
                ExtractionWarning(
                    "low_confidence",
                    "The OCR engine reported low confidence on scanned pages.",
                    {"threshold": min_conf},
                )
            )

        if page_count == 0 or (not segments and not unresolved):
            outcome = "empty"
            warnings.append(
                ExtractionWarning("no_text_found", "The PDF has no extractable text.")
            )
        elif not segments and unresolved:
            outcome = "needs_ocr"
        elif unresolved or truncated or total_pages > page_count or low_conf:
            outcome = "partial"
        else:
            outcome = "ok"

        info = {
            key: str(value)[:_MAX_META_CHARS]
            for key, value in (doc.metadata or {}).items()
            if isinstance(value, str) and value
        }
        try:
            embedded = [str(n)[:_MAX_META_CHARS] for n in doc.embfile_names()]
        except Exception:  # noqa: BLE001
            embedded = []
        metadata = {
            "page_count": total_pages,
            "pages_extracted": page_count,
            "pdf_info": info,
            "embedded_file_names": embedded,
            "pages": page_summaries,
            "ocr_pages": ocr_pages,
        }
        return ExtractionResult(
            self.name, getattr(pymupdf, "__version__", self.version), outcome, segments,
            metadata, warnings,
        )

    def _ocr_scanned_pages(
        self,
        doc: Any,
        inp: ExtractionInput,
        scanned_pages: list[int],
        summaries: list[dict[str, Any]],
        segments: list[SegmentDraft],
        warnings: list[ExtractionWarning],
    ) -> tuple[list[int], list[int], list[float]]:
        """OCR scanned pages. Returns (pages with OCR text, unresolved pages, confidences)."""
        if not scanned_pages:
            return [], [], []
        if not inp.options.get("pdf_ocr_fallback", True):
            return [], list(scanned_pages), []

        done: list[int] = []
        unresolved: list[int] = []
        confidences: list[float] = []
        max_pixels = inp.limits.max_image_pixels
        for position, number in enumerate(scanned_pages):
            page = doc[number - 1]
            rect = page.rect
            if not (rect.width > 0 and rect.height > 0):
                unresolved.append(number)
                continue
            scale = OCR_DPI / 72
            if rect.width * scale * rect.height * scale > max_pixels:
                unresolved.append(number)
                warnings.append(
                    ExtractionWarning(
                        "page_too_large_for_ocr",
                        f"Page {number} is too large to render for OCR within the limit.",
                        {"page": number},
                    )
                )
                continue
            try:
                self._ocr.version(inp.options)
                image = self._render(page)
                raw = self._ocr.recognize(image, inp.options)
            except DependencyMissingError as exc:
                unresolved.extend(scanned_pages[position:])
                warnings.append(ExtractionWarning("ocr_unavailable", exc.message))
                return done, sorted(set(unresolved)), confidences
            except ExtractionError as exc:
                unresolved.append(number)
                warnings.append(
                    ExtractionWarning(
                        "ocr_failed",
                        f"OCR failed on page {number}: {exc.message}",
                        {"page": number},
                    )
                )
                continue
            lines = group_words_into_lines(raw, image.width, image.height)
            if not lines:
                unresolved.append(number)
                continue
            sx = rect.width / image.width
            sy = rect.height / image.height
            for line in lines:
                x0, y0, x1, y1 = line.bbox
                segments.append(
                    SegmentDraft(
                        segment_type="ocr_line",
                        text=line.text,
                        locator=PdfLocator(
                            page=number,
                            bbox=(x0 * sx, y0 * sy, x1 * sx, y1 * sy),
                            page_width=float(rect.width),
                            page_height=float(rect.height),
                        ),
                        data={"words": line.words, "source": "ocr", "render_dpi": OCR_DPI},
                        engine_confidence=line.confidence,
                        language=str(inp.options.get("tesseract_langs") or "eng"),
                    )
                )
                confidences.extend(w["confidence"] for w in line.words)
            done.append(number)
            summaries[number - 1]["ocr_applied"] = True
        return done, unresolved, confidences

    @staticmethod
    def _render(page: Any) -> Any:
        from PIL import Image

        pix = page.get_pixmap(dpi=OCR_DPI, alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
