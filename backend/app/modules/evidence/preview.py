"""Rendered PDF page previews (PNG) for the evidence viewer.

The stored file is opened read-only from memory with PyMuPDF, one page is rasterized
at a capped resolution, and the PNG bytes are returned. Nothing is written to disk,
the document's scripts/links are never executed, and the original file is untouched.
"""

from __future__ import annotations

from app.core.exceptions import BadRequestError, EvidenceXError, NotFoundError

MAX_DPI = 150
MIN_DPI = 24
MAX_PREVIEW_PIXELS = 12_000_000


class PreviewUnavailableError(EvidenceXError):
    status_code = 503
    message = "PDF previews are unavailable on this server"


def render_pdf_page(data: bytes, page_number: int, dpi: int) -> bytes:
    """PNG of the 1-based ``page_number``. Raises domain errors, never library ones."""
    dpi = max(MIN_DPI, min(int(dpi), MAX_DPI))
    try:
        import pymupdf as fitz
    except ImportError as exc:
        raise PreviewUnavailableError("PyMuPDF is not installed") from exc
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - any parse failure means "not previewable"
        raise BadRequestError("the PDF could not be opened for preview") from exc
    try:
        if doc.needs_pass:
            raise BadRequestError("the PDF is password protected")
        if page_number < 1 or page_number > doc.page_count:
            raise NotFoundError("page not found")
        page = doc.load_page(page_number - 1)
        zoom = dpi / 72.0
        rect = page.rect
        while rect.width * zoom * rect.height * zoom > MAX_PREVIEW_PIXELS and zoom > 0.2:
            zoom *= 0.8
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()
