"""Synthetic sample files for processing and validation tests.

Everything here is generated test data. People, companies and addresses are
invented (``example.org`` / ``example.com`` are reserved for documentation), and
each file says so in its own content. None of it is, or is meant to look like,
real evidence.

The XLSX and EML builders produce structurally real files (written by openpyxl
and by the standard library ``email`` package), because upload validation
inspects the whole file, not just its first bytes.
"""

from __future__ import annotations

import email.policy
import email.utils
import io
import struct
import warnings
import zipfile
from datetime import date, datetime, time, timedelta, timezone
from email.message import EmailMessage

from openpyxl import Workbook
from openpyxl.utils.datetime import MAC_EPOCH

SYNTHETIC_NOTE = "SYNTHETIC TEST FIXTURE. Invented data, not real evidence."


# --- ZIP helpers ----------------------------------------------------------------


def make_zip(entries: dict[str, bytes], *, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    """A ZIP package holding ``entries`` (name -> bytes)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, payload in entries.items():
            zf.writestr(name, payload)
    return buf.getvalue()


def make_zip_with_info(infos: list[tuple[zipfile.ZipInfo, bytes]]) -> bytes:
    """A ZIP package built from explicit ZipInfo objects (duplicates, odd names)."""
    buf = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # zipfile warns on duplicate names
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for info, payload in infos:
                zf.writestr(info, payload)
    return buf.getvalue()


MINIMAL_WORKBOOK_PARTS: dict[str, bytes] = {
    "[Content_Types].xml": b'<?xml version="1.0"?><Types xmlns="x"/>',
    "xl/workbook.xml": b'<?xml version="1.0"?><workbook xmlns="x"/>',
}


def make_workbook_like_zip(extra: dict[str, bytes] | None = None, **kwargs) -> bytes:
    """A ZIP that has the two required workbook parts plus ``extra`` entries.

    It is only workbook-shaped. The ZIP guard never parses the XML, so this is
    enough to exercise every ZIP rule without a real spreadsheet.
    """
    return make_zip({**MINIMAL_WORKBOOK_PARTS, **(extra or {})}, **kwargs)


def add_zip_entry(package: bytes, name: str, payload: bytes) -> bytes:
    """Return ``package`` with one more entry appended."""
    buf = io.BytesIO(package)
    with zipfile.ZipFile(buf, "a", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, payload)
    return buf.getvalue()


def patch_zip_headers(package: bytes, signature: bytes, offset: int, new: bytes) -> bytes:
    """Overwrite ``len(new)`` bytes at ``offset`` after every ``signature`` match.

    Used to forge header fields: local file header flags (offset 6) and size
    (offset 22), central directory flags (offset 8) and size (offset 24).
    """
    out = bytearray(package)
    start = 0
    while (pos := package.find(signature, start)) != -1:
        out[pos + offset : pos + offset + len(new)] = new
        start = pos + len(signature)
    return bytes(out)


LOCAL_HEADER = b"PK\x03\x04"
CENTRAL_HEADER = b"PK\x01\x02"


def forge_end_record_entry_count(package: bytes, count: int) -> bytes:
    """Rewrite the entry count in the end-of-central-directory record."""
    out = bytearray(package)
    pos = package.rfind(b"PK\x05\x06")
    out[pos + 8 : pos + 12] = struct.pack("<HH", count, count)
    return bytes(out)


# --- XLSX -----------------------------------------------------------------------


def make_xlsx_bytes(*, with_macro_binary: bool = False) -> bytes:
    """A small synthetic workbook written by openpyxl.

    Sheets: "Payments" (a date, a datetime, a formula without a cached value),
    "Approvals" (a time-only cell) and a hidden "Internal notes" sheet.
    """
    wb = Workbook()
    payments = wb.active
    payments.title = "Payments"
    payments.append(["Payment ID", "Vendor", "Amount", "Paid on", "Note"])
    payments.append(["P-1001", "Northwind Test Supplies", 1200.5, date(2026, 10, 12), "invented"])
    payments.append(
        ["P-1002", "Contoso Test Freight", 87, datetime(2026, 10, 13, 14, 30), "invented"]
    )
    payments.append(
        ["P-1003", "Fabrikam Test Services", "=SUM(C2:C3)", None, "formula, no cached value"]
    )
    payments["D2"].number_format = "yyyy-mm-dd"
    payments["D3"].number_format = "yyyy-mm-dd hh:mm"

    approvals = wb.create_sheet("Approvals")
    approvals.append(["Approver", "Approved at"])
    approvals.append(["A. Tester", time(9, 15)])
    approvals["B2"].number_format = "hh:mm"

    hidden = wb.create_sheet("Internal notes")
    hidden.append([f"{SYNTHETIC_NOTE} (hidden sheet)"])
    hidden.sheet_state = "hidden"

    buf = io.BytesIO()
    wb.save(buf)
    data = buf.getvalue()
    if with_macro_binary:
        data = add_zip_entry(data, "xl/vbaProject.bin", b"SYNTHETIC placeholder, not a macro")
    return data


# --- EML ------------------------------------------------------------------------

_FIXED_DATE = datetime(2026, 10, 12, 9, 30, tzinfo=timezone(timedelta(hours=1)))


def make_eml_bytes() -> bytes:
    """A synthetic multipart message: plain text, HTML, and two attachments."""
    msg = EmailMessage(policy=email.policy.SMTP)
    msg["From"] = "Alex Tester <alex.tester@example.org>"
    msg["To"] = "Sam Sample <sam.sample@example.com>"
    msg["Cc"] = "records@example.org"
    msg["Subject"] = "Synthetic test message about the Q3 register"
    msg["Date"] = email.utils.format_datetime(_FIXED_DATE)
    msg["Message-ID"] = "<synthetic-0001@example.org>"
    msg.set_content(f"{SYNTHETIC_NOTE}\r\nPlease see the attached register.\r\n")
    msg.add_alternative(
        f"<html><body><p>{SYNTHETIC_NOTE}</p>"
        "<p>Please see the attached register.</p></body></html>",
        subtype="html",
    )
    msg.add_attachment(
        b"id,item\r\n1,widget\r\n",
        maintype="text",
        subtype="csv",
        filename="register.csv",
    )
    msg.add_attachment(
        b"SYNTHETIC binary placeholder",
        maintype="application",
        subtype="octet-stream",
        filename="scan.bin",
    )
    return msg.as_bytes()


def make_eml_headers_only() -> bytes:
    return b"From: alex.tester@example.org\r\nSubject: Synthetic, headers only\r\n"


def make_eml_malformed_date() -> bytes:
    """Structurally valid message whose Date header is not a date."""
    return (
        b"From: Alex Tester <alex.tester@example.org>\r\n"
        b"To: sam.sample@example.com\r\n"
        b"Subject: Synthetic message with a malformed date\r\n"
        b"Date: Someday around noon\r\n"
        b"Message-ID: <synthetic-0002@example.org>\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n" + SYNTHETIC_NOTE.encode() + b"\r\n"
    )


def make_eml_invalid_charset() -> bytes:
    """Structurally valid message whose body declares a charset that does not exist."""
    return (
        b"From: Alex Tester <alex.tester@example.org>\r\n"
        b"To: sam.sample@example.com\r\n"
        b"Subject: Synthetic message with an unknown charset\r\n"
        b"Date: Mon, 12 Oct 2026 09:30:00 +0100\r\n"
        b"Message-ID: <synthetic-0003@example.org>\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: text/plain; charset=x-no-such-charset\r\n"
        b"Content-Transfer-Encoding: 8bit\r\n"
        b"\r\n" + SYNTHETIC_NOTE.encode() + b" caf\xe9\r\n"
    )


# --- more XLSX variants ---------------------------------------------------------
#
# Expected results (asserted in tests/unit/test_xlsx_extractor.py):
#   make_xlsx_bytes()              3 sheets (one hidden). Payments: header + 3 rows.
#                                  Approvals: header + 1 row. Outcome ok; warnings
#                                  hidden_sheet, formulas_not_evaluated, no_cached_value.
#   make_xlsx_cached_formula()     the formula keeps its text AND the cached value 1287.5.
#   make_xlsx_wrong_dimension()    dimension record says A1:A1 but the sheet has 4 rows
#                                  of 3 columns; all rows are still extracted.
#   make_xlsx_sparse()             rows 1, 4 and 9 only; cells B and E empty. Row numbers
#                                  and coordinates are those of the sheet, not positions.
#   make_xlsx_1904()               date system 1904; the same serial is a different date.
#   make_xlsx_empty()              one sheet with no cells: outcome empty.


def _rewrite_zip_entry(package: bytes, name: str, transform) -> bytes:
    """Return ``package`` with one entry's bytes replaced by ``transform(old)``."""
    src = io.BytesIO(package)
    out = io.BytesIO()
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            payload = zin.read(info.filename)
            if info.filename == name:
                payload = transform(payload)
            zout.writestr(info.filename, payload)
    return out.getvalue()


def _workbook_bytes(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make_xlsx_cached_formula() -> bytes:
    """A workbook whose SUM formula carries a cached result (openpyxl cannot write one,
    so the cached value is patched into the sheet XML)."""
    import re

    wb = Workbook()
    ws = wb.active
    ws.title = "Totals"
    ws.append(["Item", "Cost"])
    ws.append(["Synthetic widget", 1200.5])
    ws.append(["Synthetic gadget", 87])
    ws.append(["Total", "=SUM(B2:B3)"])
    package = _workbook_bytes(wb)

    def patch(xml: bytes) -> bytes:
        patched, count = re.subn(rb"(<f>SUM\(B2:B3\)</f>)<v\s*/>", rb"\1<v>1287.5</v>", xml)
        assert count == 1, "expected exactly one formula cell to patch"
        return patched

    return _rewrite_zip_entry(package, "xl/worksheets/sheet1.xml", patch)


def make_xlsx_wrong_dimension() -> bytes:
    import re

    wb = Workbook()
    ws = wb.active
    ws.title = "Log"
    ws.append(["Event", "Actor", "Note"])
    ws.append(["login", "user-a", "synthetic"])
    ws.append(["export", "user-b", "synthetic"])
    ws.append(["logout", "user-a", "synthetic"])
    package = _workbook_bytes(wb)

    def patch(xml: bytes) -> bytes:
        patched, count = re.subn(rb'<dimension ref="[^"]*"\s*/>', b'<dimension ref="A1:A1"/>', xml)
        assert count == 1
        return patched

    return _rewrite_zip_entry(package, "xl/worksheets/sheet1.xml", patch)


def make_xlsx_sparse() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sparse"
    ws["A1"], ws["C1"], ws["D1"], ws["F1"] = "Ref", "Owner", "Status", "Comment"
    ws["A4"], ws["C4"], ws["F4"] = "R-1", "A. Tester", "first synthetic row"
    ws["A9"], ws["D9"] = "R-2", "open"
    return _workbook_bytes(wb)


def make_xlsx_1904() -> bytes:
    wb = Workbook()
    wb.epoch = MAC_EPOCH
    ws = wb.active
    ws.title = "Dates"
    ws.append(["Label", "When"])
    ws.append(["synthetic", date(2026, 10, 12)])
    ws["B2"].number_format = "yyyy-mm-dd"
    return _workbook_bytes(wb)


def make_xlsx_empty() -> bytes:
    wb = Workbook()
    wb.active.title = "Nothing"
    return _workbook_bytes(wb)


def make_xlsx_many_rows(count: int) -> bytes:
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Rows")
    ws.append(["n", "label"])
    for i in range(1, count + 1):
        ws.append([i, f"synthetic row {i}"])
    return _workbook_bytes(wb)


def make_xlsx_billion_laughs() -> bytes:
    """A workbook whose sheet XML declares nested entities. defusedxml must refuse it."""
    base = make_xlsx_bytes()
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE lolz ['
        b'<!ENTITY a "aaaaaaaaaa">'
        b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
        b'<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>'
        b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        b"<sheetData><row r=\"1\"><c r=\"A1\" t=\"inlineStr\"><is><t>&c;</t></is></c></row>"
        b"</sheetData></worksheet>"
    )
    return _rewrite_zip_entry(base, "xl/worksheets/sheet1.xml", lambda _old: bomb)


# --- more EML variants ----------------------------------------------------------
#
# Expected results (asserted in tests/unit/test_eml_extractor.py):
#   make_eml_bytes()            6 header segments (From, To, Cc, Subject, Date, Message-ID),
#                               1 text body, 1 HTML body, 2 attachments. Date parsed with a
#                               known zone (+01:00).
#   make_eml_malformed_date()   Date kept raw, date_iso null, warning date_unparseable.
#   make_eml_invalid_charset()  body decoded via fallback, warning charset_fallback.
#   make_eml_hidden_html()      hidden text separated, warning html_hidden_content;
#                               script and style content absent from the text.
#   make_eml_opaque()           pkcs7 body: outcome partial, warning body_not_readable.
#   make_eml_naive_date()       Date without a zone: tz_known false.
#   make_eml_odd_attachment()   attachment name with control and bidi characters is cleaned.
#   make_eml_nested_message()   message/rfc822 attachment is described, never opened.


def make_eml_hidden_html() -> bytes:
    msg = EmailMessage(policy=email.policy.SMTP)
    msg["From"] = "Alex Tester <alex.tester@example.org>"
    msg["To"] = "sam.sample@example.com"
    msg["Subject"] = "Synthetic message with hidden HTML"
    msg["Message-ID"] = "<synthetic-0004@example.org>"
    msg.set_content("Visible plain text. " + SYNTHETIC_NOTE)
    msg.add_alternative(
        "<html><head><style>p{color:red}</style><title>ignored title</title></head><body>"
        "<script>alert('should never appear')</script>"
        "<p>Visible paragraph.</p>"
        '<div style="display:none">Hidden synthetic text.</div>'
        '<p>See <a href="https://example.org/report">the report</a>.</p>'
        "</body></html>",
        subtype="html",
    )
    return msg.as_bytes()


def make_eml_opaque() -> bytes:
    return (
        b"From: Alex Tester <alex.tester@example.org>\r\n"
        b"To: sam.sample@example.com\r\n"
        b"Subject: Synthetic encrypted message\r\n"
        b"Message-ID: <synthetic-0005@example.org>\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: application/pkcs7-mime; smime-type=enveloped-data; name="smime.p7m"\r\n'
        b"Content-Transfer-Encoding: base64\r\n"
        b"\r\n"
        b"U1lOVEhFVElDIFBMQUNFSE9MREVSIChub3QgYSByZWFsIGVuY3J5cHRlZCBib2R5KQ==\r\n"
    )


def make_eml_naive_date() -> bytes:
    return (
        b"From: alex.tester@example.org\r\n"
        b"To: sam.sample@example.com\r\n"
        b"Subject: Synthetic message, date without a zone\r\n"
        b"Date: Mon, 12 Oct 2026 09:30:00 -0000\r\n"
        b"\r\nSynthetic body.\r\n"
    )


def make_eml_odd_attachment() -> bytes:
    msg = EmailMessage(policy=email.policy.SMTP)
    msg["From"] = "alex.tester@example.org"
    msg["To"] = "sam.sample@example.com"
    msg["Subject"] = "Synthetic message with an odd attachment name"
    msg.set_content("Body.")
    msg.add_attachment(
        b"SYNTHETIC",
        maintype="application",
        subtype="octet-stream",
        filename="inv\u202eoice\x07/..\\x.pdf",
    )
    return msg.as_bytes()


def make_eml_nested_message() -> bytes:
    inner = EmailMessage(policy=email.policy.SMTP)
    inner["From"] = "inner.sender@example.org"
    inner["To"] = "inner.recipient@example.com"
    inner["Subject"] = "Synthetic inner message"
    inner.set_content("Inner body that must not be extracted.")
    outer = EmailMessage(policy=email.policy.SMTP)
    outer["From"] = "alex.tester@example.org"
    outer["To"] = "sam.sample@example.com"
    outer["Subject"] = "Synthetic message with a forwarded message"
    outer.set_content("Outer body.")
    outer.add_attachment(inner)
    return outer.as_bytes()


def make_eml_duplicate_dates() -> bytes:
    return (
        b"From: alex.tester@example.org\r\n"
        b"To: sam.sample@example.com\r\n"
        b"Date: Mon, 12 Oct 2026 09:30:00 +0100\r\n"
        b"Date: Tue, 13 Oct 2026 10:00:00 +0100\r\n"
        b"Subject: Synthetic message with two Date headers\r\n"
        b"\r\nBody.\r\n"
    )


# --- PDF, image and audio -------------------------------------------------------
#
# Expected results (asserted in tests/unit/test_pdf_extractor.py, test_image_ocr.py and
# test_audio_extractor.py):
#   make_pdf_text(3)         3 pages, text blocks with page and bbox inside the page;
#                            outcome ok.
#   make_pdf_scanned()       one image-only page: outcome needs_ocr (OCR unavailable) or
#                            ocr_line segments (OCR engine present).
#   make_pdf_mixed()         page 1 text, page 2 image only: partial when OCR is off.
#   make_pdf_blank()         one blank page: outcome empty.
#   make_pdf_encrypted(True) needs a password: fails with password_required.
#   make_pdf_encrypted(False) encrypted but opens: warning encrypted_no_user_password.
#   make_pdf_corrupt()       truncated: fails with corrupt_file.
#   make_text_png(...)       known words drawn on white. make_blank_png: outcome empty.
#   make_wav(...)            sine tone; silent variant for the empty case.


def make_text_png(text: str = "SYNTHETIC SAMPLE INVOICE 4821", size: int = 56) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default(size=size)
    probe = Image.new("RGB", (1, 1))
    left, top, right, bottom = ImageDraw.Draw(probe).textbbox((0, 0), text, font=font)
    image = Image.new("RGB", (right - left + 80, bottom - top + 80), "white")
    ImageDraw.Draw(image).text((40 - left, 40 - top), text, fill="black", font=font)
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


def make_blank_png(width: int = 200, height: int = 100) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, "PNG")
    return buf.getvalue()


def make_corrupt_png() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + bytes(range(40))


def make_jpeg_with_exif() -> bytes:
    from PIL import Image

    image = Image.new("RGB", (120, 60), "white")
    exif = Image.Exif()
    exif[271] = "Synthetic Camera Co"
    exif[272] = "Model T-1"
    exif[306] = "2026:10:12 09:30:00"
    exif[274] = 1
    buf = io.BytesIO()
    image.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def make_rotated_jpeg() -> bytes:
    """A 120x60 image tagged EXIF orientation 6, which displays as 60x120."""
    from PIL import Image

    image = Image.new("RGB", (120, 60), "white")
    exif = Image.Exif()
    exif[274] = 6
    buf = io.BytesIO()
    image.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def _new_pdf():
    import pymupdf

    return pymupdf.open()


def make_pdf_text(pages: int = 3) -> bytes:
    doc = _new_pdf()
    for number in range(1, pages + 1):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), f"Synthetic page {number} heading", fontsize=16)
        page.insert_text((72, 140), f"Body text on page {number}. {SYNTHETIC_NOTE}", fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def _scanned_page(doc, text: str) -> None:
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=make_text_png(text, size=64))


def make_pdf_scanned(text: str = "SYNTHETIC SCANNED PAGE") -> bytes:
    doc = _new_pdf()
    _scanned_page(doc, text)
    data = doc.tobytes()
    doc.close()
    return data


def make_pdf_mixed() -> bytes:
    doc = _new_pdf()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Synthetic page one has a text layer.", fontsize=12)
    _scanned_page(doc, "SYNTHETIC SCANNED PAGE")
    data = doc.tobytes()
    doc.close()
    return data


def make_pdf_blank() -> bytes:
    doc = _new_pdf()
    doc.new_page(width=595, height=842)
    data = doc.tobytes()
    doc.close()
    return data


def make_pdf_encrypted(require_password: bool) -> bytes:
    import pymupdf

    doc = _new_pdf()
    page = doc.new_page()
    page.insert_text((72, 100), "Synthetic protected page", fontsize=12)
    data = doc.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="synthetic-owner",
        user_pw="synthetic-user" if require_password else "",
    )
    doc.close()
    return data


def make_pdf_corrupt() -> bytes:
    data = make_pdf_text(2)
    return data[: len(data) // 3]


def make_wav(seconds: float = 1.0, *, silent: bool = False, rate: int = 16000) -> bytes:
    import math
    import wave

    frames = bytearray()
    for n in range(int(seconds * rate)):
        sample = 0 if silent else int(12000 * math.sin(2 * math.pi * 440 * n / rate))
        frames += struct.pack("<h", sample)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(bytes(frames))
    return buf.getvalue()
