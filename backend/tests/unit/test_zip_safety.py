"""ZIP package guard for XLSX workbooks: every rejection rule, plus acceptance.

All packages are generated in memory. Nothing is written to disk.
"""

from __future__ import annotations

import io
import os
import zipfile

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.zip_safety import MB, ZipLimits, ZipSafetyError, inspect_workbook_zip
from tests.fixtures.processing_samples import (
    CENTRAL_HEADER,
    LOCAL_HEADER,
    add_zip_entry,
    forge_end_record_entry_count,
    make_workbook_like_zip,
    make_xlsx_bytes,
    make_zip,
    make_zip_with_info,
    patch_zip_headers,
)


def _code(package: bytes, limits: ZipLimits | None = None) -> str:
    with pytest.raises(ZipSafetyError) as info:
        inspect_workbook_zip(package, limits)
    return info.value.code


# --- limits and settings --------------------------------------------------------


def test_default_limits_match_the_approved_values():
    limits = ZipLimits()
    assert limits.max_entries == 2_000
    assert limits.max_total_uncompressed == 100 * MB
    assert limits.max_entry_uncompressed == 50 * MB
    assert limits.max_shared_strings == 20 * MB
    assert limits.max_ratio == 100


def test_settings_defaults_feed_the_limits():
    assert ZipLimits.from_settings(Settings()) == ZipLimits()


def test_limits_can_be_configured_from_the_environment(monkeypatch):
    monkeypatch.setenv("MAX_ZIP_ENTRIES", "10")
    monkeypatch.setenv("MAX_ZIP_UNCOMPRESSED_MB", "7")
    monkeypatch.setenv("MAX_ZIP_ENTRY_MB", "3")
    monkeypatch.setenv("MAX_SHARED_STRINGS_MB", "2")
    monkeypatch.setenv("MAX_ZIP_COMPRESSION_RATIO", "40")
    limits = ZipLimits.from_settings(Settings())
    assert limits == ZipLimits(10, 7 * MB, 3 * MB, 2 * MB, 40)


@pytest.mark.parametrize(
    "name",
    [
        "MAX_ZIP_ENTRIES",
        "MAX_ZIP_UNCOMPRESSED_MB",
        "MAX_ZIP_ENTRY_MB",
        "MAX_SHARED_STRINGS_MB",
        "MAX_ZIP_COMPRESSION_RATIO",
    ],
)
def test_limits_must_be_positive(name):
    with pytest.raises(ValidationError):
        Settings(**{name: 0})


# --- acceptance -----------------------------------------------------------------


def test_real_openpyxl_workbook_is_accepted():
    report = inspect_workbook_zip(make_xlsx_bytes())
    assert report.entry_count >= 5
    assert report.total_uncompressed > 0
    assert report.has_vba_project is False


def test_macro_binary_is_reported_not_rejected():
    report = inspect_workbook_zip(make_xlsx_bytes(with_macro_binary=True))
    assert report.has_vba_project is True


def test_directory_entries_are_allowed():
    package = make_workbook_like_zip({"xl/": b"", "xl/worksheets/": b""})
    assert inspect_workbook_zip(package).entry_count == 4


def test_small_highly_compressible_entry_is_not_a_bomb():
    # 10 KB of zeros compresses far beyond 100:1 but is below the ratio threshold.
    package = make_workbook_like_zip({"xl/worksheets/sheet1.xml": b"\x00" * 10_000})
    inspect_workbook_zip(package)


# --- not a ZIP / damaged --------------------------------------------------------


def test_signature_only_is_rejected():
    assert _code(b"PK\x03\x04" + b"\x00" * 60) == "corrupt_zip"


def test_truncated_package_is_rejected():
    package = make_xlsx_bytes()
    assert _code(package[: len(package) // 2]) == "corrupt_zip"


def test_flipped_byte_in_stored_entry_fails_the_crc_check():
    marker = b"UNIQUE-STORED-CONTENT-0123456789"
    package = make_workbook_like_zip(
        {"xl/worksheets/sheet1.xml": marker}, compression=zipfile.ZIP_STORED
    )
    position = package.index(marker)
    damaged = package[:position] + b"X" + package[position + 1 :]
    assert _code(damaged) == "corrupt_zip"


def test_non_workbook_zip_is_rejected():
    docx_like = make_zip(
        {"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<w:document/>"}
    )
    assert _code(docx_like) == "not_workbook"


def test_missing_content_types_is_rejected():
    assert _code(make_zip({"xl/workbook.xml": b"<workbook/>"})) == "not_workbook"


def test_missing_workbook_part_is_rejected():
    assert _code(make_zip({"[Content_Types].xml": b"<Types/>"})) == "not_workbook"


# --- entry count ----------------------------------------------------------------


def test_too_many_entries_is_rejected():
    package = make_workbook_like_zip({f"xl/extra{i}.xml": b"<a/>" for i in range(6)})
    assert _code(package, ZipLimits(max_entries=5)) == "too_many_entries"


def test_entry_count_at_the_limit_is_accepted():
    package = make_workbook_like_zip({f"xl/extra{i}.xml": b"<a/>" for i in range(3)})
    inspect_workbook_zip(package, ZipLimits(max_entries=5))


def test_forged_entry_count_is_rejected_before_entries_are_read():
    forged = forge_end_record_entry_count(make_workbook_like_zip(), 60_000)
    assert _code(forged) == "too_many_entries"


def test_zip64_placeholder_in_end_record_is_rejected():
    forged = forge_end_record_entry_count(make_workbook_like_zip(), 0xFFFF)
    assert _code(forged) == "zip64_unsupported"


# --- sizes ----------------------------------------------------------------------


def test_oversized_entry_is_rejected():
    big = os.urandom(2 * MB)  # incompressible, so the ratio rule is not the trigger
    package = make_workbook_like_zip({"xl/worksheets/sheet1.xml": big})
    assert _code(package, ZipLimits(max_entry_uncompressed=1 * MB)) == "entry_too_large"


def test_total_expanded_size_is_rejected():
    parts = {f"xl/worksheets/sheet{i}.xml": os.urandom(400_000) for i in range(1, 5)}
    package = make_workbook_like_zip(parts)
    limits = ZipLimits(max_total_uncompressed=1 * MB)
    assert _code(package, limits) == "total_too_large"


def test_oversized_shared_strings_is_rejected():
    package = make_workbook_like_zip({"xl/sharedStrings.xml": os.urandom(2 * MB)})
    limits = ZipLimits(max_shared_strings=1 * MB)
    assert _code(package, limits) == "shared_strings_too_large"


def test_shared_strings_cap_ignores_name_case():
    package = make_workbook_like_zip({"xl/SharedStrings.XML": os.urandom(2 * MB)})
    assert _code(package, ZipLimits(max_shared_strings=1 * MB)) == "shared_strings_too_large"


def test_default_limits_reject_a_real_expansion_bomb():
    # 60 MB of zeros deflates to roughly 60 KB. It is stopped by the 50 MB entry cap
    # (and would also trip the ratio rule); it is never expanded into memory.
    out = io.BytesIO(make_workbook_like_zip())
    with zipfile.ZipFile(out, "a", zipfile.ZIP_DEFLATED) as zf:
        with zf.open("xl/worksheets/sheet1.xml", "w") as entry:
            for _ in range(60):
                entry.write(b"\x00" * MB)
    assert _code(out.getvalue()) == "entry_too_large"


# --- compression ratio ----------------------------------------------------------


def test_excessive_compression_ratio_is_rejected():
    package = make_workbook_like_zip({"xl/worksheets/sheet1.xml": b"\x00" * (1 * MB)})
    assert _code(package, ZipLimits(max_ratio=100)) == "ratio_exceeded"


def test_ratio_limit_is_configurable():
    package = make_workbook_like_zip({"xl/worksheets/sheet1.xml": b"\x00" * (1 * MB)})
    inspect_workbook_zip(package, ZipLimits(max_ratio=100_000))


def test_overall_ratio_is_checked_across_many_medium_entries():
    # Each entry is below the per-entry threshold; together they are a bomb.
    parts = {f"xl/worksheets/sheet{i}.xml": b"\x00" * (50 * 1024) for i in range(1, 41)}
    assert _code(make_workbook_like_zip(parts), ZipLimits(max_ratio=100)) == "ratio_exceeded"


# --- header forgery -------------------------------------------------------------


def test_forged_small_declared_size_cannot_hide_a_large_entry():
    name = b"xl/worksheets/sheet1.xml"
    package = make_workbook_like_zip({"xl/worksheets/sheet1.xml": os.urandom(2 * MB)})
    small = (10).to_bytes(4, "little")
    # Forge ONLY this entry's uncompressed size, in its local and central headers.
    local_at = package.find(name) - 30
    central_at = package.rfind(name) - 46
    assert package[local_at : local_at + 4] == LOCAL_HEADER
    assert package[central_at : central_at + 4] == CENTRAL_HEADER
    forged = bytearray(package)
    forged[local_at + 22 : local_at + 26] = small
    forged[central_at + 24 : central_at + 28] = small
    # The declared size now passes every limit, so the real byte count and CRC
    # check must be what stops it.
    assert _code(bytes(forged), ZipLimits(max_entry_uncompressed=1 * MB)) in (
        "corrupt_zip",
        "entry_too_large",
    )


# --- encryption, methods, names -------------------------------------------------


def test_encrypted_entry_is_rejected():
    package = make_workbook_like_zip()
    flagged = patch_zip_headers(package, CENTRAL_HEADER, 8, b"\x01\x00")
    flagged = patch_zip_headers(flagged, LOCAL_HEADER, 6, b"\x01\x00")
    assert _code(flagged) == "encrypted_entry"


def test_unsupported_compression_is_rejected():
    package = make_workbook_like_zip(
        {"xl/worksheets/sheet1.xml": b"<a/>" * 100}, compression=zipfile.ZIP_BZIP2
    )
    assert _code(package) == "unsupported_compression"


def test_duplicate_entry_names_are_rejected():
    infos = [
        (zipfile.ZipInfo("[Content_Types].xml"), b"<Types/>"),
        (zipfile.ZipInfo("xl/workbook.xml"), b"<workbook/>"),
        (zipfile.ZipInfo("xl/workbook.xml"), b"<workbook/>"),
    ]
    assert _code(make_zip_with_info(infos)) == "duplicate_entry"


@pytest.mark.parametrize(
    "name",
    ["../escape.xml", "xl/../../escape.xml", "/absolute.xml", "C:/drive.xml"],
)
def test_unsafe_entry_names_are_rejected(name):
    infos = [
        (zipfile.ZipInfo("[Content_Types].xml"), b"<Types/>"),
        (zipfile.ZipInfo("xl/workbook.xml"), b"<workbook/>"),
        (zipfile.ZipInfo(name), b"<a/>"),
    ]
    assert _code(make_zip_with_info(infos)) == "unsafe_entry_name"


def test_rejection_messages_do_not_echo_entry_names():
    hostile = "xl/secret-looking-name-12345.xml"
    package = make_workbook_like_zip({hostile: os.urandom(2 * MB)})
    with pytest.raises(ZipSafetyError) as info:
        inspect_workbook_zip(package, ZipLimits(max_entry_uncompressed=1 * MB))
    assert "secret-looking-name" not in info.value.message


def test_nothing_is_extracted_to_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    inspect_workbook_zip(add_zip_entry(make_xlsx_bytes(), "xl/extra.xml", b"<a/>"))
    assert list(tmp_path.iterdir()) == []
