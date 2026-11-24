"""The manual-test sample files behave exactly as their README says.

Generates the samples into a temporary folder (never into ``backend/var``) and checks
upload validation and extraction for each one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.modules.evidence.validation import (
    SIGNATURE_PREFIX_LEN,
    UnsupportedFileError,
    deep_validate,
    resolve_and_validate,
)
from app.modules.processing.errors import ExtractionError
from app.modules.processing.extractors.ocr_engine import find_tesseract
from app.modules.processing.options import engine_options
from app.modules.processing.registry import build_default_registry
from tests.fixtures import generate_manual_samples as samples
from tests.fixtures.extraction import run

HAS_TESSERACT = find_tesseract() is not None
OPTIONS = engine_options(Settings())


def outcome_of(name: str, data: bytes) -> str:
    resolved = resolve_and_validate(name, data[:SIGNATURE_PREFIX_LEN])
    deep_validate(name, data)
    extractor = build_default_registry().get(resolved.mime_type)
    try:
        return run(extractor, data, mime=resolved.mime_type, options=OPTIONS).outcome
    except ExtractionError as exc:
        return exc.code


EXPECTED = {
    "ledger.csv": {"ok"},
    "register.xlsx": {"ok"},
    "totals-with-cached-formula.xlsx": {"ok"},
    "sparse-rows.xlsx": {"ok"},
    "message.eml": {"ok"},
    "hidden-html.eml": {"ok"},
    "malformed-date.eml": {"ok"},
    "encrypted-body.eml": {"partial"},
    "report.pdf": {"ok"},
    "scanned.pdf": {"ok", "partial"} if HAS_TESSERACT else {"needs_ocr"},
    "mixed-text-and-scan.pdf": {"ok", "partial"},
    "blank.pdf": {"empty"},
    "password-protected.pdf": {"password_required"},
    "invoice-scan.png": {"ok", "partial"} if HAS_TESSERACT else {"dependency_missing"},
    "blank.png": {"empty"} if HAS_TESSERACT else {"dependency_missing"},
    "broken-workbook.xlsx": {"corrupt_file"},
}


def test_every_accepted_sample_is_listed_with_an_expectation():
    assert set(samples.ACCEPTED) - {"tone.wav"} == set(EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_accepted_samples_upload_and_extract_as_documented(name):
    assert outcome_of(name, samples.ACCEPTED[name]) in EXPECTED[name]


def test_the_audio_sample_passes_upload_validation():
    data = samples.ACCEPTED["tone.wav"]
    deep_validate("tone.wav", data)
    assert resolve_and_validate("tone.wav", data[:SIGNATURE_PREFIX_LEN]).evidence_type == "audio"


@pytest.mark.parametrize("name", sorted(samples.REJECTED))
def test_rejected_samples_are_refused_at_upload(name):
    data = samples.REJECTED[name]
    with pytest.raises(UnsupportedFileError):
        resolve_and_validate(name, data[:SIGNATURE_PREFIX_LEN])
        deep_validate(name, data)


def test_sample_details_stated_in_the_readme():
    workbook = run(
        build_default_registry().get(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        samples.ACCEPTED["register.xlsx"],
    )
    assert workbook.metadata["data_row_count"] == 4
    csv = run(build_default_registry().get("text/csv"), samples.ACCEPTED["ledger.csv"])
    assert csv.metadata["data_row_count"] == 4


def test_writer_creates_every_file_and_the_readme(tmp_path):
    written = samples.write_samples(tmp_path / "out")
    names = {p.name for p in written}
    assert set(samples.ACCEPTED) <= names and set(samples.REJECTED) <= names
    assert "README.md" in names
    assert (tmp_path / "out" / "should-be-rejected" / "zip-bomb.xlsx").is_file()


def test_writer_refuses_to_write_into_the_live_data_folder():
    live = Path(samples.BACKEND_DIR) / "var" / "samples-must-not-exist"
    with pytest.raises(SystemExit):
        samples.write_samples(live)
    assert not live.exists()
