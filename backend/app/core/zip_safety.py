"""Safety checks for ZIP packages (XLSX workbooks).

One implementation is shared by upload validation and, later, by the XLSX
extractor, so both enforce exactly the same limits.

Nothing is ever extracted to disk. The package is inspected in memory in three
layers, cheapest first, and rejected before any workbook parser sees it:

1. The end-of-central-directory record is read directly, so a forged entry count
   or an oversized central directory is refused before ``zipfile`` builds one
   object per entry.
2. Declared metadata is checked: entry count, names, encryption, compression
   method, per-entry and total size, shared-strings size and compression ratio.
3. Every entry is then decompressed in bounded chunks and the REAL byte counts are
   checked against the same limits. This also verifies each entry's CRC, so a
   header that lies about an entry's size cannot get past it.

Error messages never include entry names or file content.
"""

from __future__ import annotations

import io
import struct
import zipfile
import zlib
from dataclasses import dataclass

from app.core.config import Settings, get_settings

MB = 1024 * 1024

# The compression ratio check only applies to entries at least this large. A tiny
# entry cannot be an expansion bomb (the size caps bound it) and small XML parts
# of real workbooks can compress very well.
RATIO_MIN_ENTRY_BYTES = 64 * 1024
# The same rule for the package as a whole.
RATIO_MIN_TOTAL_BYTES = 1 * MB

_CHUNK = 64 * 1024
_EOCD_SIGNATURE = b"PK\x05\x06"
_EOCD_MIN_LEN = 22
_MAX_COMMENT_LEN = 65_535
# Real workbooks need roughly 100 bytes of central directory per entry.
_CD_BYTES_PER_ENTRY = 2_048
_CD_SLACK = 65_536

REQUIRED_PARTS = ("[Content_Types].xml", "xl/workbook.xml")
_VBA_PART = "xl/vbaproject.bin"
_ALLOWED_COMPRESSION = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)

_ZIP_ERRORS = (
    zipfile.BadZipFile,
    zipfile.LargeZipFile,
    zlib.error,
    EOFError,
    NotImplementedError,
    RuntimeError,
    OSError,
    ValueError,
    OverflowError,
    struct.error,
)


@dataclass(frozen=True)
class ZipLimits:
    """Limits for a ZIP package. Defaults match the application settings."""

    max_entries: int = 2_000
    max_total_uncompressed: int = 100 * MB
    max_entry_uncompressed: int = 50 * MB
    max_shared_strings: int = 20 * MB
    max_ratio: int = 100

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> ZipLimits:
        s = settings or get_settings()
        return cls(
            max_entries=s.max_zip_entries,
            max_total_uncompressed=s.max_zip_uncompressed_mb * MB,
            max_entry_uncompressed=s.max_zip_entry_mb * MB,
            max_shared_strings=s.max_shared_strings_mb * MB,
            max_ratio=s.max_zip_compression_ratio,
        )


class ZipSafetyError(ValueError):
    """The package is unsafe or is not a workbook. ``code`` is machine readable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ZipReport:
    entry_count: int
    total_uncompressed: int
    total_compressed: int
    has_vba_project: bool


def _is_unsafe_name(name: str) -> bool:
    if not name or "\x00" in name or "\\" in name or name.startswith("/"):
        return True
    if len(name) > 1 and name[1] == ":":  # drive letter
        return True
    return any(part == ".." for part in name.split("/"))


def _is_shared_strings(name: str) -> bool:
    lowered = name.lower()
    return lowered.startswith("xl/sharedstrings") and lowered.endswith(".xml")


def _read_central_directory_summary(data: bytes, limits: ZipLimits) -> None:
    """Refuse forged entry counts and oversized central directories up front."""
    tail = data[-(_EOCD_MIN_LEN + _MAX_COMMENT_LEN) :]
    pos = tail.rfind(_EOCD_SIGNATURE)
    if pos < 0 or len(tail) - pos < _EOCD_MIN_LEN:
        raise ZipSafetyError("corrupt_zip", "The file is not a valid ZIP package.")
    total_entries, cd_size, cd_offset = struct.unpack_from("<HII", tail, pos + 10)
    if total_entries == 0xFFFF or cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF:
        raise ZipSafetyError("zip64_unsupported", "ZIP64 packages are not supported for workbooks.")
    if total_entries > limits.max_entries:
        raise ZipSafetyError(
            "too_many_entries",
            f"The ZIP package has more than {limits.max_entries} entries.",
        )
    if cd_size > limits.max_entries * _CD_BYTES_PER_ENTRY + _CD_SLACK:
        raise ZipSafetyError("central_directory_too_large", "The ZIP directory is too large.")
    if cd_offset + cd_size > len(data):
        raise ZipSafetyError("corrupt_zip", "The file is not a valid ZIP package.")


def inspect_workbook_zip(data: bytes, limits: ZipLimits | None = None) -> ZipReport:
    """Check that ``data`` is a safe, intact XLSX package. Raises ZipSafetyError.

    Does not parse any workbook XML and does not write anything to disk.
    """
    limits = limits or ZipLimits()
    _read_central_directory_summary(data, limits)

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except _ZIP_ERRORS as exc:
        raise ZipSafetyError("corrupt_zip", "The file is not a valid ZIP package.") from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > limits.max_entries:
            raise ZipSafetyError(
                "too_many_entries",
                f"The ZIP package has more than {limits.max_entries} entries.",
            )

        names = [info.filename for info in infos]
        if len(set(names)) != len(names):
            raise ZipSafetyError("duplicate_entry", "The ZIP package has duplicate entries.")

        total_declared = 0
        total_compressed = 0
        has_vba = False
        for info in infos:
            name = info.filename
            if _is_unsafe_name(name):
                raise ZipSafetyError(
                    "unsafe_entry_name", "The ZIP package has an unsafe entry name."
                )
            if info.flag_bits & 0x1 or info.flag_bits & 0x40:
                raise ZipSafetyError(
                    "encrypted_entry", "The ZIP package contains encrypted entries."
                )
            if info.compress_type not in _ALLOWED_COMPRESSION:
                raise ZipSafetyError(
                    "unsupported_compression",
                    "The ZIP package uses an unsupported compression method.",
                )
            if name.endswith("/"):
                continue  # directory entry: counted above, carries no data

            size, packed = info.file_size, info.compress_size
            if size > limits.max_entry_uncompressed:
                raise ZipSafetyError(
                    "entry_too_large",
                    f"A ZIP entry is larger than {limits.max_entry_uncompressed // MB} MB "
                    "when uncompressed.",
                )
            if _is_shared_strings(name) and size > limits.max_shared_strings:
                raise ZipSafetyError(
                    "shared_strings_too_large",
                    f"The shared strings part is larger than {limits.max_shared_strings // MB} MB.",
                )
            if size >= RATIO_MIN_ENTRY_BYTES and (packed <= 0 or size / packed > limits.max_ratio):
                raise ZipSafetyError(
                    "ratio_exceeded",
                    f"A ZIP entry compresses more than {limits.max_ratio}:1.",
                )
            total_declared += size
            total_compressed += packed
            if total_declared > limits.max_total_uncompressed:
                raise ZipSafetyError(
                    "total_too_large",
                    f"The ZIP package expands beyond {limits.max_total_uncompressed // MB} MB.",
                )
            if name.lower() == _VBA_PART:
                has_vba = True

        if total_declared >= RATIO_MIN_TOTAL_BYTES and (
            total_compressed <= 0 or total_declared / total_compressed > limits.max_ratio
        ):
            raise ZipSafetyError(
                "ratio_exceeded", f"The ZIP package compresses more than {limits.max_ratio}:1."
            )

        name_set = set(names)
        if any(part not in name_set for part in REQUIRED_PARTS):
            raise ZipSafetyError("not_workbook", "The ZIP package is not an XLSX workbook.")

        actual_total = _verify_streams(archive, infos, limits)

    return ZipReport(
        entry_count=len(infos),
        total_uncompressed=actual_total,
        total_compressed=total_compressed,
        has_vba_project=has_vba,
    )


def _verify_streams(
    archive: zipfile.ZipFile, infos: list[zipfile.ZipInfo], limits: ZipLimits
) -> int:
    """Decompress every entry in bounded chunks and check the real sizes.

    Declared sizes come from attacker-controlled headers, so they are not enough.
    Reading to the end of an entry also verifies its CRC.
    """
    actual_total = 0
    try:
        for info in infos:
            if info.filename.endswith("/"):
                continue
            entry_cap = limits.max_entry_uncompressed
            if _is_shared_strings(info.filename):
                entry_cap = min(entry_cap, limits.max_shared_strings)
            entry_bytes = 0
            with archive.open(info) as stream:
                while True:
                    chunk = stream.read(_CHUNK)
                    if not chunk:
                        break
                    entry_bytes += len(chunk)
                    actual_total += len(chunk)
                    if entry_bytes > entry_cap or entry_bytes > info.file_size:
                        raise ZipSafetyError(
                            "entry_too_large", "A ZIP entry is larger than its declared size."
                        )
                    if actual_total > limits.max_total_uncompressed:
                        raise ZipSafetyError(
                            "total_too_large",
                            f"The ZIP package expands beyond "
                            f"{limits.max_total_uncompressed // MB} MB.",
                        )
    except ZipSafetyError:
        raise
    except _ZIP_ERRORS as exc:
        raise ZipSafetyError("corrupt_zip", "The ZIP package is damaged or incomplete.") from exc
    return actual_total
