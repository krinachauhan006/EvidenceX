"""Licence and producer notices written into every PDF that EvidenceX generates.

PDFs are rendered with PyMuPDF (MuPDF), which EvidenceX uses under the GNU AGPL-3.0.
Artifex's licensing guidance for the AGPL build asks that the copyright and producer
metadata of generated PDFs be preserved. PyMuPDF writes no producer of its own, so the
``producer`` entry names it, with its copyright holder and licence, and ``creator``
names EvidenceX, its licence and where its source code is published. Nothing here is
case data; these strings are the same for every document.

If you deploy a modified version, point ``SOURCE_CODE_URL`` at the source of that
version (AGPL-3.0 section 13).
"""

from __future__ import annotations

SOURCE_CODE_URL = "https://github.com/krinachauhan006/EvidenceX"


def producer_notice() -> str:
    import pymupdf

    return (
        f"PyMuPDF {pymupdf.VersionBind} (MuPDF {pymupdf.VersionFitz}), "
        "Copyright (C) Artifex Software, Inc., GNU AGPL-3.0"
    )


def creator_notice() -> str:
    return f"EvidenceX (GNU AGPL-3.0), source: {SOURCE_CODE_URL}"


def pdf_metadata(title: str, subject: str = "") -> dict[str, str]:
    """The full metadata dictionary for ``Document.set_metadata`` (which replaces every
    key, so producer and creator must be included on each call)."""
    return {
        "title": title,
        "subject": subject,
        "creator": creator_notice(),
        "producer": producer_notice(),
    }
