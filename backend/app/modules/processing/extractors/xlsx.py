"""XLSX extractor (openpyxl, read-only, defusedxml).

Rules:
- The package is inspected with the shared ZIP guard BEFORE openpyxl sees it, with the
  same limits as upload validation. Nothing is extracted to disk.
- Formulas are never evaluated. A formula cell keeps its formula text and its cached
  value; a missing cached value is reported, never computed.
- Dates keep every representation available: ISO text, the number format, the
  workbook date system and a numeric serial. No timezone is invented and a date-only
  or time-only cell is never turned into a full timestamp.
- Read-only mode does not expose merged cells, comments, charts or images. They are
  not extracted, and ``metadata.limitations`` says so.
"""

from __future__ import annotations

import datetime as dt
import io
import re
import zipfile
from itertools import zip_longest
from typing import Any

from app.core.zip_safety import ZipSafetyError, inspect_workbook_zip
from app.modules.processing.errors import (
    CorruptFileError,
    DependencyMissingError,
    ExtractionError,
    LimitExceededError,
    PasswordRequiredError,
    UnsupportedContentError,
)
from app.modules.processing.extractors.base import (
    ExtractionInput,
    ExtractionResult,
    ExtractionWarning,
    SegmentDraft,
)
from app.modules.processing.extractors.csv_extractor import build_header_keys
from app.modules.processing.locators import XlsxLocator

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_LIMIT_CODES = frozenset(
    {
        "too_many_entries",
        "central_directory_too_large",
        "entry_too_large",
        "total_too_large",
        "shared_strings_too_large",
        "ratio_exceeded",
    }
)
LIMITATIONS = ["merged_cells", "cell_comments", "charts", "embedded_images", "pivot_tables"]

_QUOTED = re.compile(r'"[^"]*"|\\.|_.|\*.')
_BRACKET = re.compile(r"\[(?![hmsHMS]+\])[^\]]*\]")


def classify_number_format(fmt: str | None) -> tuple[bool, bool]:
    """(has_date_part, has_time_part) of an Excel number format."""
    if not fmt or fmt == "General":
        return False, False
    cleaned = _BRACKET.sub("", _QUOTED.sub("", fmt)).lower()
    cleaned = cleaned.split(";")[0]
    has_time = bool(re.search(r"[hs]|am/pm|a/p|\[h|\[m|\[s", cleaned))
    has_date = bool(re.search(r"[yd]", cleaned))
    if not has_date and not has_time and "m" in cleaned:
        has_date = True  # a bare month token
    return has_date, has_time


def _serial(value: Any, epoch: Any) -> float | None:
    try:
        from openpyxl.utils.datetime import to_excel

        if isinstance(value, dt.datetime):
            return float(to_excel(value, epoch))
        if isinstance(value, dt.date):
            return float(to_excel(dt.datetime.combine(value, dt.time()), epoch))
        if isinstance(value, dt.time):
            seconds = value.hour * 3600 + value.minute * 60 + value.second
            return (seconds + value.microsecond / 1e6) / 86400
        if isinstance(value, dt.timedelta):
            return value.total_seconds() / 86400
    except Exception:  # noqa: BLE001 - the serial is supplementary
        return None
    return None


def describe_temporal(value: Any, number_format: str | None, epoch: Any) -> dict[str, Any] | None:
    """Fields for a date/time cell, or None when ``value`` is not temporal."""
    if not isinstance(value, (dt.datetime, dt.date, dt.time, dt.timedelta)):
        return None
    has_date, has_time = classify_number_format(number_format)
    info: dict[str, Any] = {}
    if isinstance(value, dt.timedelta):
        info.update(type_hint="duration", value=str(value))
    elif isinstance(value, dt.time):
        info.update(type_hint="time", value=value.isoformat())
    elif isinstance(value, dt.datetime):
        midnight = value.time() == dt.time(0, 0)
        if has_time and not has_date:
            # A time format applied to a number of a day or more: keep only the time
            # of day (the serial below preserves the day count). No date is invented.
            info.update(type_hint="time", value=value.time().isoformat())
        elif not has_time and midnight:
            info.update(type_hint="date", value=value.date().isoformat())
        else:
            info.update(type_hint="datetime", value=value.isoformat())
    else:
        info.update(type_hint="date", value=value.isoformat())
    serial = _serial(value, epoch)
    if serial is not None:
        info["serial"] = serial
        info["serial_source"] = "derived"  # recomputed from the parsed value
    info["date_system"] = _date_system(epoch)
    return info


def _date_system(epoch: Any) -> str:
    return "1904" if getattr(epoch, "year", 1899) == 1904 else "1900"


def _plain_hint(value: Any) -> str:
    if value is None or value == "":
        return "empty"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "decimal"
    return "text"


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _display(cell: dict[str, Any]) -> str:
    value = cell.get("value")
    if value is None or value == "":
        return str(cell.get("formula") or "")
    return str(value)


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


class XlsxExtractor:
    name = "xlsx"
    version = "1"

    def extract(self, inp: ExtractionInput) -> ExtractionResult:
        limits = inp.limits
        data = inp.data

        if data.startswith(_OLE_MAGIC):
            raise PasswordRequiredError(
                "The workbook is password-protected or in a legacy format and cannot be read."
            )
        try:
            report = inspect_workbook_zip(data, limits.zip_limits())
        except ZipSafetyError as exc:
            if exc.code in _LIMIT_CODES:
                raise LimitExceededError(exc.message) from exc
            if exc.code == "encrypted_entry":
                raise PasswordRequiredError(exc.message) from exc
            raise CorruptFileError(exc.message) from exc

        try:
            import openpyxl
            from openpyxl import load_workbook
        except ImportError as exc:
            raise DependencyMissingError(
                "openpyxl is not installed. Install it with: pip install openpyxl"
            ) from exc
        if not getattr(openpyxl.xml, "DEFUSEDXML", False):
            raise DependencyMissingError(
                "defusedxml is not installed, so workbooks cannot be read safely. "
                "Install it with: pip install defusedxml"
            )

        wb_formulas = wb_values = None
        try:
            wb_formulas = self._open(load_workbook, data, data_only=False)
            wb_values = self._open(load_workbook, data, data_only=True)
            return self._read(wb_formulas, wb_values, inp, report.has_vba_project)
        finally:
            for wb in (wb_formulas, wb_values):
                if wb is not None:
                    try:
                        wb.close()
                    except Exception:  # noqa: BLE001
                        pass

    @staticmethod
    def _open(load_workbook: Any, data: bytes, *, data_only: bool) -> Any:
        try:
            return load_workbook(
                io.BytesIO(data), read_only=True, data_only=data_only, keep_links=False
            )
        except ExtractionError:
            raise
        except (zipfile.BadZipFile, KeyError, OSError, EOFError) as exc:
            raise CorruptFileError("The workbook could not be read.") from exc
        except Exception as exc:  # noqa: BLE001
            if _caused_by_defusedxml(exc):
                raise UnsupportedContentError(
                    "The workbook contains XML constructs that are not allowed."
                ) from exc
            raise CorruptFileError("The workbook could not be read.") from exc

    def _read(
        self, wb_f: Any, wb_v: Any, inp: ExtractionInput, has_macro: bool
    ) -> ExtractionResult:
        limits = inp.limits
        epoch = getattr(wb_f, "epoch", None) or dt.datetime(1899, 12, 30)
        warnings: list[ExtractionWarning] = []
        segments: list[SegmentDraft] = []

        sheets_meta: list[dict[str, Any]] = []
        data_rows = 0
        total_chars = 0
        formulas = missing_cached = truncated_cells = 0
        stop_reason: str | None = None
        non_empty_sheets = 0

        values_by_name = {ws.title: ws for ws in wb_v.worksheets}
        for ws_f in wb_f.worksheets:
            title = ws_f.title
            state = getattr(ws_f, "sheet_state", "visible")
            meta: dict[str, Any] = {"name": title, "state": state, "data_rows": 0}
            sheets_meta.append(meta)
            if state != "visible":
                warnings.append(
                    ExtractionWarning(
                        "hidden_sheet",
                        f"The worksheet '{title}' is {state}. It was extracted and flagged.",
                        {"sheet": title, "state": state},
                    )
                )
            if stop_reason:
                meta["skipped"] = True
                continue
            ws_v = values_by_name.get(title)
            for ws in (ws_f, ws_v):
                if ws is not None and hasattr(ws, "reset_dimensions"):
                    ws.reset_dimensions()  # do not trust a wrong dimension record

            headers_raw: list[str] | None = None
            header_keys: list[str] = []
            header_row: int | None = None
            rows_f = ws_f.iter_rows()
            rows_v = ws_v.iter_rows() if ws_v is not None else iter(())
            for row_no, (row_f, row_v) in enumerate(zip_longest(rows_f, rows_v, fillvalue=()), 1):
                cells = self._row_cells(
                    row_f, row_v, row_no, header_keys, epoch, limits.max_cell_chars
                )
                if not cells:
                    continue
                formulas += sum(1 for c in cells if "formula" in c)
                missing_cached += sum(1 for c in cells if c.get("no_cached_value"))
                truncated_cells += sum(1 for c in cells if c.get("truncated"))
                first_col, last_col = cells[0]["_col"], cells[-1]["_col"]
                span = f"{_letters(first_col)}{row_no}:{_letters(last_col)}{row_no}"
                for cell in cells:
                    cell.pop("_col")

                if headers_raw is None:
                    width = last_col
                    by_pos: dict[int, str] = {}
                    for cell in cells:
                        by_pos[int(cell["coord_col"])] = str(_display(cell))
                    headers_raw = [by_pos.get(i, "") for i in range(1, width + 1)]
                    header_keys, adjusted = build_header_keys(headers_raw)
                    header_row = row_no
                    for cell in cells:
                        cell["column"] = header_keys[int(cell["coord_col"]) - 1]
                    for cell in cells:
                        cell.pop("coord_col")
                    if adjusted:
                        warnings.append(
                            ExtractionWarning(
                                "header_keys_generated",
                                f"Blank or repeated headers on '{title}' were given unique "
                                "working names. The raw headers are preserved.",
                                {"sheet": title, "count": adjusted},
                            )
                        )
                    segments.append(
                        SegmentDraft(
                            segment_type="table_header",
                            text=" | ".join(headers_raw),
                            locator=XlsxLocator(sheet=title, row=row_no, range=span),
                            data={
                                "headers_raw": headers_raw,
                                "header_keys": header_keys,
                                "cells": cells,
                            },
                        )
                    )
                    continue

                if data_rows >= limits.max_tabular_rows:
                    stop_reason = "row_limit_reached"
                    break
                for cell in cells:
                    index = int(cell.pop("coord_col")) - 1
                    cell["column"] = (
                        header_keys[index]
                        if index < len(header_keys)
                        else f"extra_{index - len(header_keys) + 1}"
                    )
                row_text = " | ".join(
                    f"{c['column']}: {_display(c)}" for c in cells if _display(c).strip()
                )
                if total_chars + len(row_text) > limits.max_extracted_chars:
                    stop_reason = "char_limit_reached"
                    break
                total_chars += len(row_text)
                segments.append(
                    SegmentDraft(
                        segment_type="table_row",
                        text=row_text or None,
                        locator=XlsxLocator(sheet=title, row=row_no, range=span),
                        data={"cells": cells},
                    )
                )
                data_rows += 1
                meta["data_rows"] += 1

            meta["header_row"] = header_row
            meta["column_count"] = len(header_keys)
            if headers_raw is None:
                warnings.append(
                    ExtractionWarning(
                        "empty_sheet",
                        f"The worksheet '{title}' has no content.",
                        {"sheet": title},
                    )
                )
            else:
                non_empty_sheets += 1

        chartsheets = [getattr(c, "title", "") for c in getattr(wb_f, "chartsheets", [])]
        if chartsheets:
            warnings.append(
                ExtractionWarning(
                    "chartsheet_skipped",
                    "Chart sheets contain no cell data and were not extracted.",
                    {"sheets": chartsheets},
                )
            )
        if has_macro:
            warnings.append(
                ExtractionWarning(
                    "contains_macro_binary",
                    "The workbook contains a macro binary (vbaProject.bin). It was not run "
                    "or read.",
                )
            )
        if formulas:
            warnings.append(
                ExtractionWarning(
                    "formulas_not_evaluated",
                    f"{formulas} formula cell(s) were kept as text with their cached "
                    "values. Formulas are never calculated.",
                    {"count": formulas},
                )
            )
        if missing_cached:
            warnings.append(
                ExtractionWarning(
                    "no_cached_value",
                    f"{missing_cached} formula cell(s) have no cached value, so their "
                    "value is unknown.",
                    {"count": missing_cached},
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
            if non_empty_sheets:
                warnings.append(ExtractionWarning("no_data_rows", "The workbook has no data rows."))
        else:
            outcome = "ok"

        props = getattr(wb_f, "properties", None)
        metadata = {
            "date_system": _date_system(epoch),
            "sheet_count": len(sheets_meta),
            "sheets": sheets_meta,
            "data_row_count": data_rows,
            "creator": getattr(props, "creator", None),
            "last_modified_by": getattr(props, "lastModifiedBy", None),
            "created": _iso(getattr(props, "created", None)),
            "modified": _iso(getattr(props, "modified", None)),
            "title": getattr(props, "title", None),
            "limitations": LIMITATIONS,
        }
        return ExtractionResult(self.name, self.version, outcome, segments, metadata, warnings)

    @staticmethod
    def _row_cells(
        row_f: Any,
        row_v: Any,
        row_no: int,
        header_keys: list[str],
        epoch: Any,
        max_cell_chars: int,
    ) -> list[dict[str, Any]]:
        cells: list[dict[str, Any]] = []
        for col, (cf, cv) in enumerate(zip_longest(row_f, row_v, fillvalue=None), 1):
            raw = getattr(cf, "value", None)
            if raw is None or raw == "":
                continue
            number_format = getattr(cf, "number_format", None)
            cell: dict[str, Any] = {
                "coord": f"{_letters(col)}{row_no}",
                "index": col - 1,
                "coord_col": col,
                "_col": col,
                "number_format": number_format if number_format not in (None, "General") else None,
            }
            if getattr(cf, "data_type", None) == "f" or (isinstance(raw, str) and raw[:1] == "="):
                cached = getattr(cv, "value", None)
                cell["formula"] = str(raw)[:max_cell_chars]
                cell["no_cached_value"] = cached is None
                shown = cached
            else:
                shown = raw
            temporal = describe_temporal(shown, number_format, epoch)
            if temporal is not None:
                cell.update(temporal)
            else:
                cell["value"] = _jsonable(shown)
                if getattr(cf, "data_type", None) == "e" and "formula" not in cell:
                    cell["type_hint"] = "error"
                else:
                    cell["type_hint"] = _plain_hint(shown)
                if "formula" in cell and shown is None:
                    cell["type_hint"] = "unknown"  # no cached value: the result is not known
            if isinstance(cell.get("value"), str) and len(cell["value"]) > max_cell_chars:
                cell["value"] = cell["value"][:max_cell_chars]
                cell["truncated"] = True
            cells.append(cell)
        return cells


def _caused_by_defusedxml(exc: BaseException | None) -> bool:
    """openpyxl wraps parser errors, so follow the cause chain."""
    seen = 0
    while exc is not None and seen < 10:
        if type(exc).__module__.startswith("defusedxml"):
            return True
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return False


def _letters(col: int) -> str:
    from openpyxl.utils import get_column_letter

    return get_column_letter(col)
