"""Upload validation: extension, content signature (magic bytes), and modality.

Untrusted uploads are validated by BOTH their extension and their actual content
signature. The client-supplied MIME type and filename are never trusted on their
own. The resolved ``mime_type`` returned here comes from this server-side mapping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.zip_safety import ZipLimits, ZipSafetyError, inspect_workbook_zip

# Number of leading bytes sufficient to recognize every supported signature.
SIGNATURE_PREFIX_LEN = 32


@dataclass(frozen=True)
class ResolvedType:
    evidence_type: str  # "document" | "image" | "audio" | "tabular" | "email"
    mime_type: str


class UnsupportedFileError(ValueError):
    """The file is not an accepted type (bad extension or signature mismatch)."""


# Supported extensions -> (modality, canonical mime).
_EXTENSIONS: dict[str, ResolvedType] = {
    ".pdf": ResolvedType("document", "application/pdf"),
    ".png": ResolvedType("image", "image/png"),
    ".jpg": ResolvedType("image", "image/jpeg"),
    ".jpeg": ResolvedType("image", "image/jpeg"),
    ".webp": ResolvedType("image", "image/webp"),
    ".wav": ResolvedType("audio", "audio/wav"),
    ".mp3": ResolvedType("audio", "audio/mpeg"),
    ".m4a": ResolvedType("audio", "audio/mp4"),
    # Stage 3: structured formats.
    ".csv": ResolvedType("tabular", "text/csv"),
    ".xlsx": ResolvedType(
        "tabular", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
    ".eml": ResolvedType("email", "message/rfc822"),
    # Phase 2: video (decoded with PyAV/FFmpeg; sampled frames + soundtrack).
    ".mp4": ResolvedType("video", "video/mp4"),
    ".mov": ResolvedType("video", "video/quicktime"),
    ".webm": ResolvedType("video", "video/webm"),
}
VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".webm"})
# ISO-BMFF / QuickTime top-level box types that may come first in a .mov/.mp4 file.
_QT_FIRST_BOXES = (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip")

# Sample size for text-format checks (CSV).
TEXT_SAMPLE_LEN = 65_536
_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")
_UTF8_BOM = b"\xef\xbb\xbf"

_ZIP_LOCAL_HEADER = b"PK\x03\x04"
# Legacy / password-encrypted Office files use the OLE compound-file container.
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# EML: a header field name is printable ASCII without a colon, followed by one.
_EML_HEADER_LINE = re.compile(rb"^[\x21-\x39\x3b-\x7e]+:")
_EML_MBOX_FROM_LINE = re.compile(rb"^From \S")
_EML_HEADER_END = re.compile(rb"\r?\n\r?\n")
# At least one of these must be present. Content-Type, Date and Subject alone are
# deliberately not enough: HTTP responses and many logs carry them too.
_EML_IDENTITY_HEADERS = frozenset(
    {
        "from",
        "to",
        "cc",
        "bcc",
        "sender",
        "reply-to",
        "message-id",
        "received",
        "return-path",
        "mime-version",
        "delivered-to",
    }
)

SUPPORTED_EXTENSIONS: tuple[str, ...] = tuple(_EXTENSIONS.keys())


def extension_of(filename: str) -> str:
    """Return the lowercase extension (including the dot), or "" if none."""
    name = filename.strip().lower()
    dot = name.rfind(".")
    if dot == -1:
        return ""
    return name[dot:]


def _matches_signature(prefix: bytes, expected_ext: str) -> bool:
    """Return whether the content prefix is consistent with the expected modality.

    Signatures are matched by modality rather than exact extension where formats
    share a container (e.g. jpg/jpeg).
    """
    resolved = _EXTENSIONS[expected_ext]
    modality = resolved.evidence_type

    if expected_ext == ".pdf":
        return prefix.startswith(b"%PDF-")

    if expected_ext == ".png":
        return prefix.startswith(b"\x89PNG\r\n\x1a\n")

    if expected_ext in (".jpg", ".jpeg"):
        return prefix.startswith(b"\xff\xd8\xff")

    if expected_ext == ".webp":
        return prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP"

    if expected_ext == ".wav":
        return prefix.startswith(b"RIFF") and prefix[8:12] == b"WAVE"

    if expected_ext == ".mp3":
        # ID3 tag, or an MPEG audio frame sync (0xFF followed by 0xEx/0xFx).
        if prefix.startswith(b"ID3"):
            return True
        return len(prefix) >= 2 and prefix[0] == 0xFF and (prefix[1] & 0xE0) == 0xE0

    if expected_ext == ".m4a":
        # ISO base-media container: an "ftyp" box at offset 4.
        return len(prefix) >= 12 and prefix[4:8] == b"ftyp"

    if expected_ext == ".mp4":
        return len(prefix) >= 12 and prefix[4:8] == b"ftyp"

    if expected_ext == ".mov":
        return len(prefix) >= 12 and prefix[4:8] in _QT_FIRST_BOXES

    if expected_ext == ".webm":
        return prefix.startswith(b"\x1a\x45\xdf\xa3")  # EBML header (Matroska/WebM)

    if expected_ext == ".csv":
        return _is_text_like(prefix)

    if expected_ext == ".xlsx":
        return prefix.startswith(_ZIP_LOCAL_HEADER)

    if expected_ext == ".eml":
        # RFC 5322 messages are 7-bit/8-bit text, never UTF-16.
        return not prefix.startswith(_UTF16_BOMS) and _is_text_like(prefix)

    # Should be unreachable given the extension allow-list.
    return modality != ""


def _is_text_like(sample: bytes) -> bool:
    """Reject content that is clearly binary rather than delimited text.

    UTF-16 text legitimately contains NUL bytes, so a UTF-16 byte-order mark is
    accepted. Otherwise known binary signatures and NUL bytes are rejected.
    """
    if sample.startswith(_UTF16_BOMS):
        return True
    if sample.startswith(_UTF8_BOM):
        sample = sample[len(_UTF8_BOM) :]
    binary_starts = (
        b"%PDF-",
        b"\x89PNG\r\n\x1a\n",
        b"PK\x03\x04",
        b"\xff\xd8\xff",
        b"\x7fELF",
        b"MZ\x90\x00",
        b"\xd0\xcf\x11\xe0",
        b"\x1f\x8b",
    )
    if sample.startswith(binary_starts):
        return False
    if sample[:4] == b"RIFF" and sample[8:12] in (b"WAVE", b"WEBP", b"AVI "):
        return False
    if sample[:3] == b"ID3" or sample[4:8] == b"ftyp":
        return False
    return b"\x00" not in sample


def _validate_eml(content: bytes) -> None:
    """Require a real RFC 5322 header block, so arbitrary text is not accepted.

    Only the structure is checked. Odd values (a malformed Date, an unknown
    charset) are accepted here and reported later as extraction warnings.
    """
    sample = content[:TEXT_SAMPLE_LEN]
    end = _EML_HEADER_END.search(sample)
    if end is not None:
        block = sample[: end.start()]
    elif len(content) <= TEXT_SAMPLE_LEN:
        block = sample  # a message that is only headers
    else:
        raise UnsupportedFileError("no email header block found in the start of the file (.eml)")

    if any(b < 32 and b not in (9, 10, 13) for b in block):
        raise UnsupportedFileError("email headers contain binary or control characters (.eml)")

    names: set[str] = set()
    for index, line in enumerate(block.splitlines()):
        if index == 0 and _EML_MBOX_FROM_LINE.match(line):
            continue  # an mbox "From " separator line is tolerated
        if line[:1] in (b" ", b"\t"):  # folded continuation of the previous header
            if not names:
                raise UnsupportedFileError("the file does not start with email headers (.eml)")
            continue
        match = _EML_HEADER_LINE.match(line)
        if match is None:
            raise UnsupportedFileError("the file does not start with email headers (.eml)")
        names.add(line[: match.end() - 1].decode("ascii").lower())

    if not names & _EML_IDENTITY_HEADERS:
        raise UnsupportedFileError("no common email header (From, To, Message-ID) found (.eml)")


def deep_validate(filename: str, content: bytes, *, zip_limits: ZipLimits | None = None) -> None:
    """Content checks that need more than the 32-byte signature prefix.

    Runs on the already-buffered upload, after ``resolve_and_validate``. Raises
    ``UnsupportedFileError`` when the content is not what the extension claims.
    Formats without a deep check are accepted unchanged.

    ``zip_limits`` applies to ``.xlsx``; it defaults to the application settings.
    """
    ext = extension_of(filename)
    if ext == ".xlsx":
        try:
            inspect_workbook_zip(content, zip_limits or ZipLimits.from_settings())
        except ZipSafetyError as exc:
            raise UnsupportedFileError(f"{exc.message} (.xlsx)") from exc
        return
    if ext == ".eml":
        _validate_eml(content)
        return
    if ext == ".csv":
        sample = content[:TEXT_SAMPLE_LEN]
        if not _is_text_like(sample):
            raise UnsupportedFileError("file content is binary, not delimited text (.csv)")
        if sample.startswith(_UTF16_BOMS):
            return
        # Text files contain almost no control characters besides tab, LF and CR.
        allowed = {9, 10, 13}
        controls = sum(1 for b in sample if b < 32 and b not in allowed)
        if sample and controls / len(sample) > 0.05:
            raise UnsupportedFileError("file content contains too many control characters (.csv)")


def resolve_and_validate(filename: str, prefix: bytes) -> ResolvedType:
    """Validate an upload by extension and content signature.

    Raises ``UnsupportedFileError`` if the extension is not supported or the
    content signature does not match it.
    """
    ext = extension_of(filename)
    if ext not in _EXTENSIONS:
        raise UnsupportedFileError(
            f"unsupported file type '{ext or filename}'. "
            f"supported: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
    if not _matches_signature(prefix, ext):
        if ext == ".xlsx" and prefix.startswith(_OLE_MAGIC):
            raise UnsupportedFileError(
                "this is an OLE-format Office file (a password-protected or legacy "
                "workbook), not an .xlsx package. Remove the password or re-save it as .xlsx"
            )
        raise UnsupportedFileError(f"file content does not match its '{ext}' extension")
    return _EXTENSIONS[ext]
