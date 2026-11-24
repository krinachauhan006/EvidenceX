"""CSV extractor (Python standard library ``csv``).

Fidelity rules:
- Cell values are the exact source strings. Nothing is trimmed, converted or
  reformatted, and dates are never parsed.
- ``type_hint`` is advisory metadata only.
- Row numbers count every record the reader returns, blank ones included, so they
  match the row numbers a spreadsheet program shows. Blank records produce no
  segment.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter

from app.modules.processing.errors import CorruptFileError
from app.modules.processing.extractors.base import (
    ExtractionInput,
    ExtractionResult,
    ExtractionWarning,
    SegmentDraft,
)
from app.modules.processing.locators import CsvLocator

# Quoted fields can legitimately be large. Per-cell truncation is enforced by us.
csv.field_size_limit(16 * 1024 * 1024)

_DELIMITER_SAMPLE_CHARS = 65_536
_MAX_LISTED_ROWS = 20

_INT_RE = re.compile(r"^[+-]?\d+$")
_INT_GROUPED_RE = re.compile(r"^[+-]?\d{1,3}(,\d{3})+$")
_DEC_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+)$")
_DEC_GROUPED_RE = re.compile(r"^[+-]?\d{1,3}(,\d{3})+\.\d+$")


def type_hint(value: str) -> str:
    """Advisory type of a cell. The value itself is never changed."""
    s = value.strip()
    if s == "":
        return "empty"
    if _INT_RE.match(s) or _INT_GROUPED_RE.match(s):
        return "integer"
    if _DEC_RE.match(s) or _DEC_GROUPED_RE.match(s):
        return "decimal"
    if s.lower() in ("true", "false"):
        return "boolean"
    return "text"


def decode_text(data: bytes) -> tuple[str, str, list[ExtractionWarning]]:
    """Decode with strict codecs, in order: UTF-8 (BOM aware), UTF-16 (BOM only),
    Windows-1252, then Latin-1 as a last resort. Returns (text, encoding, warnings).
    """
    warnings: list[ExtractionWarning] = []

    if data.startswith(b"\xef\xbb\xbf"):
        try:
            return data.decode("utf-8-sig"), "utf-8-sig", warnings
        except UnicodeDecodeError:
            pass  # falls through to the fallbacks below
    elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16"), "utf-16", warnings
        except UnicodeDecodeError as exc:
            raise CorruptFileError("The file declares UTF-16 but could not be decoded.") from exc

    if b"\x00" in data:
        raise CorruptFileError("The file contains binary data and is not delimited text.")

    try:
        return data.decode("utf-8"), "utf-8", warnings
    except UnicodeDecodeError:
        pass

    try:
        text, encoding = data.decode("cp1252"), "cp1252"
    except UnicodeDecodeError:
        text, encoding = data.decode("latin-1"), "latin-1"
    warnings.append(
        ExtractionWarning(
            "encoding_assumed",
            f"The file is not valid UTF-8 and was decoded as {encoding}.",
            {"encoding": encoding},
        )
    )
    return text, encoding, warnings


_CANDIDATE_DELIMITERS = (",", ";", "\t", "|")
_DELIMITER_SAMPLE_RECORDS = 25
_MIN_CONSISTENCY = 0.8


def _field_counts(sample: str, delimiter: str) -> list[int]:
    """Field count of each of the first records, parsed with ``delimiter``."""
    counts: list[int] = []
    reader = csv.reader(io.StringIO(sample, newline=""), delimiter=delimiter, quotechar='"')
    try:
        for record in reader:
            if record:
                counts.append(len(record))
            if len(counts) >= _DELIMITER_SAMPLE_RECORDS:
                break
    except csv.Error:
        return []
    return counts


def detect_delimiter(text: str) -> tuple[str, ExtractionWarning | None]:
    """Pick the delimiter that splits the sample into a consistent number of
    fields (at least two). Deterministic: ties go to the earlier candidate in
    ``, ; tab |``. A file with a single column is read with a comma, no warning.
    """
    sample = text[:_DELIMITER_SAMPLE_CHARS]
    best: tuple[float, int, str] | None = None  # (consistency, fields, delimiter)
    for delimiter in _CANDIDATE_DELIMITERS:
        counts = _field_counts(sample, delimiter)
        if not counts:
            continue
        fields, hits = Counter(counts).most_common(1)[0]
        consistency = hits / len(counts)
        if fields < 2 or consistency < _MIN_CONSISTENCY:
            continue
        # Prefer higher consistency, then more fields; max() keeps the first on ties.
        if best is None or (consistency, fields) > (best[0], best[1]):
            best = (consistency, fields, delimiter)
    if best is not None:
        return best[2], None

    comma_counts = _field_counts(sample, ",")
    if comma_counts and all(c == 1 for c in comma_counts):
        return ",", None  # one column; nothing to split
    return ",", ExtractionWarning(
        "delimiter_assumed", "The delimiter could not be detected; a comma was assumed."
    )


def build_header_keys(raw: list[str]) -> tuple[list[str], int]:
    """Unique working keys for columns. Raw headers are kept separately.

    Blank headers become ``column_N``; repeats become ``Name__2``, ``Name__3``.
    Returns (keys, number_of_adjusted_headers).
    """
    keys: list[str] = []
    used: set[str] = set()
    adjusted = 0
    for i, header in enumerate(raw):
        base = header if header.strip() else f"column_{i + 1}"
        key, n = base, 1
        while key in used:
            n += 1
            key = f"{base}__{n}"
        used.add(key)
        if key != header:
            adjusted += 1
        keys.append(key)
    return keys, adjusted


class CsvExtractor:
    name = "csv"
    version = "1"

    def extract(self, inp: ExtractionInput) -> ExtractionResult:
        limits = inp.limits
        text, encoding, warnings = decode_text(inp.data)

        if not text.strip():
            warnings.append(ExtractionWarning("empty_file", "The file contains no data."))
            return ExtractionResult(
                self.name, self.version, "empty", [], {"encoding": encoding}, warnings
            )

        delimiter, delimiter_warning = detect_delimiter(text)
        if delimiter_warning:
            warnings.append(delimiter_warning)

        reader = csv.reader(
            io.StringIO(text, newline=""),
            delimiter=delimiter,
            quotechar='"',
            doublequote=True,
            strict=False,
        )

        segments: list[SegmentDraft] = []
        headers_raw: list[str] | None = None
        header_keys: list[str] = []
        header_row: int | None = None
        row_no = 0
        prev_line = 0
        blank_rows = 0
        data_rows = 0
        ragged_count = 0
        ragged_first: list[int] = []
        truncated_cells = 0
        total_chars = 0
        stop_reason: str | None = None

        try:
            for record in reader:
                row_no += 1
                start_line = prev_line + 1
                prev_line = reader.line_num

                if not record:  # a blank line
                    blank_rows += 1
                    continue

                if headers_raw is None:
                    headers_raw = list(record)
                    header_keys, adjusted = build_header_keys(headers_raw)
                    header_row = row_no
                    if adjusted:
                        warnings.append(
                            ExtractionWarning(
                                "header_keys_generated",
                                "Blank or repeated headers were given unique working names. "
                                "The raw headers are preserved.",
                                {"count": adjusted},
                            )
                        )
                    segments.append(
                        SegmentDraft(
                            segment_type="table_header",
                            text=" | ".join(headers_raw),
                            locator=CsvLocator(row=row_no, line=start_line),
                            data={"headers_raw": headers_raw, "header_keys": header_keys},
                        )
                    )
                    continue

                if data_rows >= limits.max_tabular_rows:
                    stop_reason = "row_limit_reached"
                    break

                cells = []
                for i, raw_value in enumerate(record):
                    value = raw_value
                    cell_truncated = len(value) > limits.max_cell_chars
                    if cell_truncated:
                        value = value[: limits.max_cell_chars]
                        truncated_cells += 1
                    key = (
                        header_keys[i]
                        if i < len(header_keys)
                        else f"extra_{i - len(header_keys) + 1}"
                    )
                    cell = {
                        "column": key,
                        "index": i,
                        "value": value,
                        "type_hint": type_hint(value),
                    }
                    if cell_truncated:
                        cell["truncated"] = True
                    cells.append(cell)

                if len(record) != len(header_keys):
                    ragged_count += 1
                    if len(ragged_first) < _MAX_LISTED_ROWS:
                        ragged_first.append(row_no)

                row_text = " | ".join(
                    f"{c['column']}: {c['value']}" for c in cells if str(c["value"]).strip()
                )
                if total_chars + len(row_text) > limits.max_extracted_chars:
                    stop_reason = "char_limit_reached"
                    break
                total_chars += len(row_text)

                segments.append(
                    SegmentDraft(
                        segment_type="table_row",
                        text=row_text or None,
                        locator=CsvLocator(row=row_no, line=start_line),
                        data={"cells": cells},
                    )
                )
                data_rows += 1
        except csv.Error as exc:
            raise CorruptFileError(
                f"The file could not be parsed as CSV near line {reader.line_num}."
            ) from exc

        if ragged_count:
            warnings.append(
                ExtractionWarning(
                    "ragged_rows",
                    f"{ragged_count} row(s) have a different number of cells than the header. "
                    "They were kept exactly as read.",
                    {"count": ragged_count, "first_rows": ragged_first},
                )
            )
        if truncated_cells:
            warnings.append(
                ExtractionWarning(
                    "cell_truncated",
                    f"{truncated_cells} cell(s) exceeded {limits.max_cell_chars} characters "
                    "and were truncated.",
                    {"count": truncated_cells},
                )
            )
        if stop_reason == "row_limit_reached":
            warnings.append(
                ExtractionWarning(
                    "row_limit_reached",
                    f"Only the first {limits.max_tabular_rows} data rows were extracted.",
                    {"limit": limits.max_tabular_rows},
                )
            )
        elif stop_reason == "char_limit_reached":
            warnings.append(
                ExtractionWarning(
                    "char_limit_reached",
                    "Extraction stopped because the total text limit was reached.",
                    {"limit": limits.max_extracted_chars},
                )
            )

        if stop_reason or truncated_cells:
            outcome = "partial"
        elif data_rows == 0:
            outcome = "empty"
            warnings.append(ExtractionWarning("no_data_rows", "The file has no data rows."))
        else:
            outcome = "ok"

        metadata = {
            "encoding": encoding,
            "delimiter": delimiter,
            "header_row": header_row,
            "headers_raw": headers_raw,
            "header_keys": header_keys,
            "column_count": len(header_keys),
            "rows_read": row_no,
            "data_row_count": data_rows,
            "blank_rows": blank_rows,
        }
        return ExtractionResult(self.name, self.version, outcome, segments, metadata, warnings)
