"""Tiny in-memory sample files with valid content signatures per modality.

These are the smallest byte sequences that pass the Stage 2 signature checks. They
are NOT fully valid media files — Stage 2 only validates signatures and never
decodes content. Real decoding/extraction belongs to Stage 3+.
"""

from __future__ import annotations

from tests.fixtures.processing_samples import make_eml_bytes, make_xlsx_bytes

# A minimal real PDF (header + trivial body). %PDF- signature is what matters here.
PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog>>endobj\n"
    b"trailer<</Root 1 0 R>>\n"
    b"%%EOF\n"
)

# PNG 8-byte magic followed by a stub IHDR-ish chunk. Signature is the first 8 bytes.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 20

# JPEG SOI + APP0/JFIF marker start.
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 16

# WEBP: RIFF container with WEBP fourcc at offset 8.
WEBP_BYTES = b"RIFF" + b"\x20\x00\x00\x00" + b"WEBP" + b"VP8 " + b"\x00" * 16

# WAV: RIFF container with WAVE fourcc at offset 8.
WAV_BYTES = b"RIFF" + b"\x24\x00\x00\x00" + b"WAVE" + b"fmt " + b"\x00" * 16

# MP3: ID3v2 tag header.
MP3_BYTES = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 16

# M4A: ISO base-media box with "ftyp" at offset 4 and an M4A brand.
M4A_BYTES = b"\x00\x00\x00\x20ftypM4A \x00\x00\x00\x00M4A mp42isom" + b"\x00" * 8

# MP4: ISO base-media box with "ftyp" at offset 4 and an isom brand.
MP4_BYTES = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 8

# MOV: QuickTime file starting with an "ftyp" box and the "qt  " brand.
MOV_BYTES = b"\x00\x00\x00\x14ftypqt  \x00\x00\x02\x00qt  " + b"\x00" * 12

# WEBM: EBML header magic.
WEBM_BYTES = b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\xf7\x81\x01webm" + b"\x00" * 12

# CSV: plain UTF-8 text with a header row.
CSV_BYTES = b"date,vendor,amount\n2026-10-12,Acme Ltd,1200.50\n2026-10-13,Bolt Co,87\n"


# XLSX and EML are checked in full at upload (ZIP package inspection, header
# block), so their samples are real generated files. Both are synthetic.
XLSX_BYTES = make_xlsx_bytes()
EML_BYTES = make_eml_bytes()


SAMPLES: dict[str, tuple[str, bytes, str]] = {
    # ext: (filename, bytes, expected_evidence_type)
    "pdf": ("report.pdf", PDF_BYTES, "document"),
    "png": ("photo.png", PNG_BYTES, "image"),
    "jpg": ("photo.jpg", JPEG_BYTES, "image"),
    "jpeg": ("photo.jpeg", JPEG_BYTES, "image"),
    "webp": ("photo.webp", WEBP_BYTES, "image"),
    "wav": ("call.wav", WAV_BYTES, "audio"),
    "mp3": ("call.mp3", MP3_BYTES, "audio"),
    "m4a": ("call.m4a", M4A_BYTES, "audio"),
    "csv": ("ledger.csv", CSV_BYTES, "tabular"),
    "xlsx": ("workbook.xlsx", XLSX_BYTES, "tabular"),
    "eml": ("message.eml", EML_BYTES, "email"),
    "mp4": ("clip.mp4", MP4_BYTES, "video"),
    "mov": ("clip.mov", MOV_BYTES, "video"),
    "webm": ("clip.webm", WEBM_BYTES, "video"),
}
