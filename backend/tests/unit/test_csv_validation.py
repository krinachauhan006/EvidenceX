"""Upload validation for CSV (signature prefix plus deep content check)."""

from __future__ import annotations

import pytest

from app.modules.evidence.validation import (
    UnsupportedFileError,
    deep_validate,
    resolve_and_validate,
)
from tests.fixtures.sample_files import CSV_BYTES, JPEG_BYTES, PDF_BYTES, PNG_BYTES, WAV_BYTES


def _check(name: str, content: bytes):
    resolved = resolve_and_validate(name, content[:32])
    deep_validate(name, content)
    return resolved


def test_csv_resolves_to_tabular():
    resolved = _check("ledger.csv", CSV_BYTES)
    assert resolved.evidence_type == "tabular"
    assert resolved.mime_type == "text/csv"


def test_utf16_csv_with_bom_is_accepted():
    _check("ledger.csv", "a,b\n1,2\n".encode("utf-16"))


def test_utf8_bom_csv_is_accepted():
    _check("ledger.csv", b"\xef\xbb\xbfa,b\n1,2\n")


def test_cp1252_csv_is_accepted():
    _check("ledger.csv", "name\nJosé\n".encode("cp1252"))


@pytest.mark.parametrize(
    "content",
    [PNG_BYTES, JPEG_BYTES, PDF_BYTES, WAV_BYTES, b"PK\x03\x04" + b"\x00" * 30],
    ids=["png", "jpeg", "pdf", "wav", "zip"],
)
def test_binary_files_named_csv_are_rejected(content):
    with pytest.raises(UnsupportedFileError):
        _check("data.csv", content)


def test_nul_bytes_without_utf16_bom_rejected():
    with pytest.raises(UnsupportedFileError):
        _check("data.csv", b"a,b\n1,\x00\x00\n")


def test_control_character_heavy_file_rejected():
    noisy = b"a,b\n" + bytes([1, 2, 3, 4, 5, 6, 7, 8]) * 50
    with pytest.raises(UnsupportedFileError):
        _check("data.csv", noisy)


def test_other_formats_are_unaffected_by_deep_validation():
    deep_validate("report.pdf", PDF_BYTES)  # no deep check, no error
    deep_validate("photo.png", PNG_BYTES)
