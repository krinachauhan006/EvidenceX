"""Which Tesseract language packs are installed, and how to add more.

Language data is never downloaded by the application. ``language_report`` only
lists the ``.traineddata`` files Tesseract itself reports.
"""

from __future__ import annotations

import re
from typing import Any

from app.modules.processing.extractors.ocr_engine import find_tesseract

# Display names for common packs (ISO 639-2/T codes as used by Tesseract).
NAMES = {
    "eng": "English",
    "fra": "French",
    "deu": "German",
    "spa": "Spanish",
    "ita": "Italian",
    "por": "Portuguese",
    "nld": "Dutch",
    "rus": "Russian",
    "ukr": "Ukrainian",
    "pol": "Polish",
    "tur": "Turkish",
    "ara": "Arabic",
    "fas": "Persian",
    "heb": "Hebrew",
    "hin": "Hindi",
    "ben": "Bengali",
    "guj": "Gujarati",
    "tam": "Tamil",
    "urd": "Urdu",
    "chi_sim": "Chinese (simplified)",
    "chi_tra": "Chinese (traditional)",
    "jpn": "Japanese",
    "kor": "Korean",
    "vie": "Vietnamese",
    "tha": "Thai",
    "ell": "Greek",
    "osd": "Orientation & script detection",
}
_CODE = re.compile(r"^[a-z]{3}(?:_[a-z]{3,4})?$")
INSTALL_HELP = (
    "Download the language's .traineddata file from the tesseract-ocr/tessdata "
    "repository and copy it into Tesseract's tessdata folder (on Windows usually "
    r"C:\Program Files\Tesseract-OCR\tessdata). Restart the backend afterwards. "
    "EvidenceX never downloads language data itself."
)


def installed_languages(tesseract_cmd: str = "") -> list[str] | None:
    """Installed codes, or None when Tesseract is not available."""
    path = find_tesseract(tesseract_cmd)
    if path is None:
        return None
    try:
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = path
        return sorted(str(x) for x in pytesseract.get_languages(config=""))
    except Exception:  # noqa: BLE001 - treated as "unavailable", reported to the user
        return None


def validate_languages(value: str, installed: list[str] | None) -> tuple[str, list[str]]:
    """Normalize 'eng+deu' and return (value, missing codes)."""
    codes = [c for c in value.replace(",", "+").split("+") if c]
    if not codes or any(not _CODE.match(c) for c in codes):
        raise ValueError("OCR languages must be Tesseract codes such as 'eng' or 'eng+deu'")
    missing = [c for c in codes if installed is None or c not in installed]
    return "+".join(dict.fromkeys(codes)), missing


def language_report(tesseract_cmd: str, default_langs: str) -> dict[str, Any]:
    installed = installed_languages(tesseract_cmd)
    return {
        "engine_available": installed is not None,
        "default": default_langs,
        "installed": [
            {"code": c, "name": NAMES.get(c, c), "usable_for_text": c != "osd"}
            for c in (installed or [])
        ],
        "orientation_detection": bool(installed and "osd" in installed),
        "install_help": INSTALL_HELP,
    }
