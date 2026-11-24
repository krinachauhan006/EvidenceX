"""CSV extractor: fidelity, encodings, delimiters, row numbering, limits."""

from __future__ import annotations

import pytest

from app.modules.processing.errors import CorruptFileError
from app.modules.processing.extractors.base import ExtractionInput
from app.modules.processing.extractors.csv_extractor import (
    CsvExtractor,
    build_header_keys,
    detect_delimiter,
    type_hint,
)
from app.modules.processing.limits import ExtractionLimits
from app.modules.processing.locators import CsvLocator


def run(data: bytes | str, **limits):
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return CsvExtractor().extract(
        ExtractionInput(
            data=raw,
            filename="x.csv",
            mime_type="text/csv",
            sha256="0" * 64,
            limits=ExtractionLimits(**limits),
        )
    )


def codes(result) -> list[str]:
    return [w.code for w in result.warnings]


def cells(segment) -> dict[str, str]:
    return {c["column"]: c["value"] for c in segment.data["cells"]}


# --- basics ---------------------------------------------------------------------


def test_basic_header_and_rows():
    result = run("date,vendor,amount\n2026-10-12,Acme Ltd,1200.50\n2026-10-13,Bolt Co,87\n")
    assert result.outcome == "ok"
    assert result.extractor == "csv"
    assert [s.segment_type for s in result.segments] == ["table_header", "table_row", "table_row"]
    header, row2, row3 = result.segments
    assert header.locator == CsvLocator(row=1, line=1)
    assert header.data["headers_raw"] == ["date", "vendor", "amount"]
    assert row2.locator == CsvLocator(row=2, line=2)
    assert row3.locator == CsvLocator(row=3, line=3)
    assert cells(row2) == {"date": "2026-10-12", "vendor": "Acme Ltd", "amount": "1200.50"}
    assert result.metadata["delimiter"] == ","
    assert result.metadata["data_row_count"] == 2
    assert result.metadata["header_keys"] == ["date", "vendor", "amount"]


def test_values_are_preserved_exactly():
    src = (
        'id,note,when,calc\n'
        '007,"  padded  ",01/02/2026,=SUM(A1:A2)\n'
        '"1,200.00","say ""hi""",2026-02-30,TRUE\n'
    )
    result = run(src)
    first = cells(result.segments[1])
    assert first == {"id": "007", "note": "  padded  ", "when": "01/02/2026", "calc": "=SUM(A1:A2)"}
    second = cells(result.segments[2])
    assert second["id"] == "1,200.00"
    assert second["note"] == 'say "hi"'
    assert second["when"] == "2026-02-30"  # an impossible date is NOT validated or fixed


def test_dates_are_never_parsed():
    result = run("when\n01/02/2026\n2026-10-12\n")
    hints = [c["type_hint"] for s in result.segments[1:] for c in s.data["cells"]]
    assert hints == ["text", "text"]


def test_extraction_is_deterministic():
    data = "a,b\n1,2\n3,4\n"
    assert run(data) == run(data)


# --- encodings ------------------------------------------------------------------


def test_utf8_bom_is_stripped_from_first_header():
    result = run(b"\xef\xbb\xbfname,qty\nbolt,3\n")
    assert result.metadata["encoding"] == "utf-8-sig"
    assert result.metadata["headers_raw"][0] == "name"
    assert "encoding_assumed" not in codes(result)


def test_utf16_with_bom():
    result = run("name,qty\nbolt,3\n".encode("utf-16"))
    assert result.metadata["encoding"] == "utf-16"
    assert cells(result.segments[1]) == {"name": "bolt", "qty": "3"}


def test_cp1252_fallback_warns_and_keeps_characters():
    result = run("name,city\nJosé,Zürich\n".encode("cp1252"))
    assert result.metadata["encoding"] == "cp1252"
    assert "encoding_assumed" in codes(result)
    assert cells(result.segments[1]) == {"name": "José", "city": "Zürich"}


def test_utf8_non_ascii_without_warning():
    result = run("name\nZoë\n")
    assert result.metadata["encoding"] == "utf-8"
    assert codes(result) == []
    assert cells(result.segments[1]) == {"name": "Zoë"}


def test_binary_content_is_corrupt():
    with pytest.raises(CorruptFileError):
        run(b"a,b\n1,\x00\x01\x02\n")


# --- delimiters -----------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("a;b;c\n1;2;3\n4;5;6\n", ";"),
        ("a\tb\tc\n1\t2\t3\n4\t5\t6\n", "\t"),
        ("a|b|c\n1|2|3\n4|5|6\n", "|"),
        ("a,b,c\n1,2,3\n4,5,6\n", ","),
    ],
)
def test_delimiter_detection(text, expected):
    assert detect_delimiter(text) == (expected, None)


def test_semicolon_file_with_commas_in_text():
    text = "name;note\nA;hello, world\nB;ok, fine\nC;x, y, z\n"
    assert detect_delimiter(text)[0] == ";"


def test_single_column_file_needs_no_warning():
    delimiter, warning = detect_delimiter("name\nalpha\nbeta\n")
    assert delimiter == ","
    assert warning is None


def test_undetectable_delimiter_warns():
    _, warning = detect_delimiter("a,b\nc;d;e\nf|g|h|i\n")
    assert warning is not None and warning.code == "delimiter_assumed"


# --- row numbering --------------------------------------------------------------


def test_quoted_newline_keeps_row_and_line_numbers_distinct():
    result = run('a,b\n"x\ny",2\nz,3\n')
    _, multi, after = result.segments
    assert multi.locator == CsvLocator(row=2, line=2)
    assert cells(multi)["a"] == "x\ny"
    assert after.locator == CsvLocator(row=3, line=4)  # row 3 starts on physical line 4


def test_blank_lines_count_as_rows_but_produce_no_segment():
    result = run("a,b\n\n1,2\n")
    assert len(result.segments) == 2  # header + one data row
    assert result.segments[1].locator == CsvLocator(row=3, line=3)
    assert result.metadata["blank_rows"] == 1


def test_leading_blank_lines_before_header():
    result = run("\n\na,b\n1,2\n")
    assert result.metadata["header_row"] == 3
    assert result.segments[0].locator == CsvLocator(row=3, line=3)
    assert result.segments[1].locator == CsvLocator(row=4, line=4)


# --- headers --------------------------------------------------------------------


def test_blank_and_duplicate_headers_get_unique_working_keys():
    result = run("a,,a\n1,2,3\n")
    assert result.metadata["headers_raw"] == ["a", "", "a"]
    assert result.metadata["header_keys"] == ["a", "column_2", "a__2"]
    assert "header_keys_generated" in codes(result)
    assert cells(result.segments[1]) == {"a": "1", "column_2": "2", "a__2": "3"}


def test_build_header_keys_avoids_collision_with_generated_name():
    keys, adjusted = build_header_keys(["column_2", "", "x"])
    assert len(set(keys)) == 3
    assert adjusted == 1


# --- ragged rows ----------------------------------------------------------------


def test_ragged_rows_are_kept_and_flagged():
    result = run("a,b,c\n1,2,3,4\n5,6\n7,8,9\n")
    long_row, short_row, ok_row = result.segments[1:]
    assert cells(long_row) == {"a": "1", "b": "2", "c": "3", "extra_1": "4"}
    assert cells(short_row) == {"a": "5", "b": "6"}
    assert len(cells(ok_row)) == 3
    warning = next(w for w in result.warnings if w.code == "ragged_rows")
    assert warning.detail == {"count": 2, "first_rows": [2, 3]}
    assert result.outcome == "ok"


def test_unterminated_quote_does_not_crash():
    result = run('a,b\n"unterminated,1\nnext,2\n')
    assert result.segments[0].segment_type == "table_header"
    assert len(result.segments) >= 2  # the content is kept, not dropped


# --- empty and edge inputs -------------------------------------------------------


def test_whitespace_only_file_is_empty():
    result = run("  \n\n \t\n")
    assert result.outcome == "empty"
    assert result.segments == []
    assert "empty_file" in codes(result)


def test_header_only_file_is_empty_but_keeps_header():
    result = run("a,b\n")
    assert result.outcome == "empty"
    assert "no_data_rows" in codes(result)
    assert [s.segment_type for s in result.segments] == ["table_header"]


# --- limits ---------------------------------------------------------------------


def test_row_limit_truncates_and_is_partial():
    data = "a\n" + "".join(f"{i}\n" for i in range(5))
    result = run(data, max_tabular_rows=2)
    assert result.outcome == "partial"
    assert sum(1 for s in result.segments if s.segment_type == "table_row") == 2
    assert "row_limit_reached" in codes(result)


def test_cell_truncation_is_flagged():
    result = run("a\nabcdefghij\n", max_cell_chars=5)
    cell = result.segments[1].data["cells"][0]
    assert cell["value"] == "abcde"
    assert cell["truncated"] is True
    assert result.outcome == "partial"
    assert "cell_truncated" in codes(result)


def test_character_limit_stops_extraction():
    data = "a\n" + "".join("x" * 20 + "\n" for _ in range(10))
    result = run(data, max_extracted_chars=60)
    assert result.outcome == "partial"
    assert "char_limit_reached" in codes(result)


# --- type hints -----------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("", "empty"),
        ("   ", "empty"),
        ("42", "integer"),
        ("-7", "integer"),
        ("007", "integer"),
        ("1,200", "integer"),
        ("3.14", "decimal"),
        ("1,200.50", "decimal"),
        (".5", "decimal"),
        ("true", "boolean"),
        ("FALSE", "boolean"),
        ("hello", "text"),
        ("2026-10-12", "text"),
        ("12abc", "text"),
    ],
)
def test_type_hint(value, expected):
    assert type_hint(value) == expected
