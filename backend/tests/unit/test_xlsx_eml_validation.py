"""Upload validation for .xlsx and .eml (signature prefix plus deep content check)."""

from __future__ import annotations

import os

import pytest

from app.core.zip_safety import MB, ZipLimits
from app.modules.evidence.validation import (
    SIGNATURE_PREFIX_LEN,
    SUPPORTED_EXTENSIONS,
    UnsupportedFileError,
    deep_validate,
    resolve_and_validate,
)
from tests.fixtures.processing_samples import (
    make_eml_bytes,
    make_eml_headers_only,
    make_eml_invalid_charset,
    make_eml_malformed_date,
    make_workbook_like_zip,
    make_xlsx_bytes,
)
from tests.fixtures.sample_files import (
    CSV_BYTES,
    JPEG_BYTES,
    PDF_BYTES,
    PNG_BYTES,
    WAV_BYTES,
)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _check(name: str, content: bytes, **kwargs):
    resolved = resolve_and_validate(name, content[:SIGNATURE_PREFIX_LEN])
    deep_validate(name, content, **kwargs)
    return resolved


# --- registration ---------------------------------------------------------------


def test_new_extensions_are_supported():
    assert ".xlsx" in SUPPORTED_EXTENSIONS
    assert ".eml" in SUPPORTED_EXTENSIONS


def test_xlsx_resolves_to_tabular_with_ooxml_mime():
    resolved = _check("book.xlsx", make_xlsx_bytes())
    assert (resolved.evidence_type, resolved.mime_type) == ("tabular", XLSX_MIME)


def test_eml_resolves_to_email_with_rfc822_mime():
    resolved = _check("mail.eml", make_eml_bytes())
    assert (resolved.evidence_type, resolved.mime_type) == ("email", "message/rfc822")


def test_extension_matching_is_case_insensitive():
    _check("BOOK.XLSX", make_xlsx_bytes())
    _check("MAIL.EML", make_eml_bytes())


# --- XLSX -----------------------------------------------------------------------


def test_workbook_with_macro_binary_is_accepted_at_upload():
    # Extraction (a later step) reports it as a warning; upload does not refuse it.
    _check("book.xlsx", make_xlsx_bytes(with_macro_binary=True))


@pytest.mark.parametrize(
    "content",
    [PNG_BYTES, JPEG_BYTES, PDF_BYTES, WAV_BYTES, CSV_BYTES, make_eml_bytes()],
    ids=["png", "jpeg", "pdf", "wav", "csv", "eml"],
)
def test_other_formats_named_xlsx_are_rejected(content):
    with pytest.raises(UnsupportedFileError):
        _check("book.xlsx", content)


def test_ole_container_gets_a_specific_message():
    ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600
    with pytest.raises(UnsupportedFileError) as info:
        _check("protected.xlsx", ole)
    message = str(info.value)
    assert "OLE" in message
    assert "password" in message


def test_zip_that_is_not_a_workbook_is_rejected():
    # Same length, so the package stays structurally intact; only the name differs.
    broken = make_workbook_like_zip().replace(b"xl/workbook.xml", b"xl/Workbook.xml")
    with pytest.raises(UnsupportedFileError, match=r"\.xlsx"):
        _check("book.xlsx", broken)


def test_truncated_workbook_is_rejected():
    package = make_xlsx_bytes()
    with pytest.raises(UnsupportedFileError):
        _check("book.xlsx", package[: len(package) // 2])


def test_zip_limits_are_passed_through():
    package = make_workbook_like_zip({f"xl/p{i}.xml": b"<a/>" for i in range(6)})
    _check("book.xlsx", package)  # fine under the defaults
    with pytest.raises(UnsupportedFileError, match="more than 5 entries"):
        _check("book.xlsx", package, zip_limits=ZipLimits(max_entries=5))


def test_expansion_bomb_is_rejected_with_default_limits():
    package = make_workbook_like_zip({"xl/worksheets/sheet1.xml": b"\x00" * (5 * MB)})
    with pytest.raises(UnsupportedFileError, match="compresses more than 100:1"):
        _check("book.xlsx", package)


def test_oversized_entry_is_rejected_with_configured_limit():
    package = make_workbook_like_zip({"xl/worksheets/sheet1.xml": os.urandom(2 * MB)})
    with pytest.raises(UnsupportedFileError):
        _check("book.xlsx", package, zip_limits=ZipLimits(max_entry_uncompressed=1 * MB))


# --- EML ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        make_eml_bytes(),
        make_eml_headers_only(),
        make_eml_malformed_date(),
        make_eml_invalid_charset(),
        b"From: a@example.org\nSubject: LF line endings\n\nbody\n",
        b"Subject: folded\r\nFrom: a@example.org,\r\n b@example.org\r\n\r\nbody",
        b"From alex@example.org Mon Oct 12 09:30:00 2026\nFrom: a@example.org\n\nbody",
        b"MIME-VERSION: 1.0\r\n\r\n",
        b"Received: from mail.example.org\r\n\r\n",
    ],
    ids=[
        "multipart-sample",
        "headers-only",
        "malformed-date",
        "invalid-charset",
        "lf-endings",
        "folded-header",
        "mbox-separator-line",
        "header-name-case",
        "received-only",
    ],
)
def test_structurally_valid_messages_are_accepted(content):
    _check("mail.eml", content)


@pytest.mark.parametrize(
    "content",
    [
        b"just some prose with no headers at all\n",
        b'{"From": "a@example.org"}\n',
        b"id,item\n1,widget\n",
        b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<html></html>",
        b"Date: Mon, 12 Oct 2026 09:30:00 +0100\r\nSubject: no identity header\r\n\r\nbody",
        b"X-Custom: only custom headers\r\n\r\nbody",
        b"\r\nFrom: a@example.org\r\n\r\nbody",
        b" folded-first: nothing to continue\r\nFrom: a@example.org\r\n\r\n",
        b"Not a header: value\r\nFrom: a@example.org\r\n\r\n",
        b"From: a@example.org\r\nthis line is not a header\r\n\r\nbody",
        b"From: a@example.org\r\nSubject: bad\x01control\r\n\r\nbody",
    ],
    ids=[
        "prose",
        "json",
        "csv",
        "http-response",
        "no-identity-header",
        "custom-headers-only",
        "leading-blank-line",
        "continuation-first",
        "space-in-field-name",
        "non-header-line-in-block",
        "control-character",
    ],
)
def test_text_that_is_not_an_email_is_rejected(content):
    with pytest.raises(UnsupportedFileError):
        _check("mail.eml", content)


def test_binary_headers_are_rejected():
    with pytest.raises(UnsupportedFileError):
        _check("mail.eml", b"From: a@example.org\r\nSubject: x\x00y\r\n\r\nbody")


@pytest.mark.parametrize(
    "content",
    [PNG_BYTES, JPEG_BYTES, PDF_BYTES, WAV_BYTES, make_xlsx_bytes()],
    ids=["png", "jpeg", "pdf", "wav", "xlsx"],
)
def test_binary_files_named_eml_are_rejected(content):
    with pytest.raises(UnsupportedFileError):
        _check("mail.eml", content)


def test_utf16_text_is_rejected_as_eml():
    with pytest.raises(UnsupportedFileError):
        _check("mail.eml", "From: a@example.org\r\n\r\nbody".encode("utf-16"))


def test_header_block_must_end_within_the_sample():
    endless = b"From: a@example.org\r\n" + b"X-Pad: " + b"a" * 70_000
    with pytest.raises(UnsupportedFileError, match="header block"):
        _check("mail.eml", endless + b"\r\n\r\nbody")


def test_large_body_after_valid_headers_is_accepted():
    body = b"x" * 200_000
    _check("mail.eml", b"From: a@example.org\r\nSubject: big\r\n\r\n" + body)


def test_eight_bit_header_values_are_accepted():
    _check("mail.eml", "From: José <jose@example.org>\r\n\r\nbody".encode())


def test_rejection_messages_do_not_echo_file_content():
    secret = b"TOP-SECRET-PHRASE-98765"
    with pytest.raises(UnsupportedFileError) as info:
        _check("mail.eml", secret + b" is not an email\n")
    assert "TOP-SECRET" not in str(info.value)
