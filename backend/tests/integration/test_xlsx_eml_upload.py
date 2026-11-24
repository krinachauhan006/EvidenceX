"""Upload of .xlsx and .eml through the HTTP API (validation only, no extraction).

Extraction itself is covered by the extractor tests and the foundation workflows.
"""

from __future__ import annotations

import hashlib
import io
import os
import uuid

import pytest

from app.core.config import Settings
from app.core.exceptions import BadRequestError
from app.core.zip_safety import MB
from app.modules.evidence.service import EvidenceService
from tests.fixtures.processing_samples import (
    make_eml_bytes,
    make_eml_invalid_charset,
    make_eml_malformed_date,
    make_workbook_like_zip,
    make_xlsx_bytes,
)
from tests.fixtures.sample_files import CSV_BYTES, PNG_BYTES, SAMPLES

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _make_case(client, title="Workbook and mail") -> str:
    res = client.post("/api/cases", json={"title": title, "description": None})
    assert res.status_code == 201
    return res.json()["id"]


def _post(client, case_id, filename, content):
    return client.post(
        f"/api/cases/{case_id}/evidence",
        files={"file": (filename, content, "application/octet-stream")},
    )


def _stored_files(tmp_path) -> list:
    root = tmp_path / "storage"
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


# --- accepted -------------------------------------------------------------------


@pytest.mark.parametrize(
    "ext,expected_type,expected_mime",
    [("xlsx", "tabular", XLSX_MIME), ("eml", "email", "message/rfc822")],
)
def test_upload_accepts_synthetic_samples(client, ext, expected_type, expected_mime):
    case_id = _make_case(client)
    filename, content, _ = SAMPLES[ext]

    res = _post(client, case_id, filename, content)

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["evidence_type"] == expected_type
    assert body["mime_type"] == expected_mime
    assert body["byte_size"] == len(content)
    assert body["sha256"] == hashlib.sha256(content).hexdigest()
    assert body["processing_status"] == "pending"
    assert body["processing_error"] is None
    assert "storage_path" not in body


@pytest.mark.parametrize(
    "filename,content",
    [
        ("macro.xlsx", make_xlsx_bytes(with_macro_binary=True)),
        ("odd-date.eml", make_eml_malformed_date()),
        ("odd-charset.eml", make_eml_invalid_charset()),
    ],
    ids=["macro-binary", "malformed-date", "invalid-charset"],
)
def test_odd_but_structurally_valid_files_are_accepted(client, filename, content):
    case_id = _make_case(client)
    assert _post(client, case_id, filename, content).status_code == 201


def test_accepted_file_downloads_byte_identical(client):
    case_id = _make_case(client)
    filename, content, _ = SAMPLES["xlsx"]
    created = _post(client, case_id, filename, content).json()
    res = client.get(f"/api/cases/{case_id}/evidence/{created['id']}/download")
    assert res.status_code == 200
    assert res.content == content


@pytest.mark.parametrize("ext", ["xlsx", "eml"])
def test_accepted_file_can_be_processed(client, ext):
    case_id = _make_case(client)
    filename, content, _ = SAMPLES[ext]
    evidence_id = _post(client, case_id, filename, content).json()["id"]

    res = client.post(f"/api/cases/{case_id}/evidence/{evidence_id}/process")

    assert res.status_code == 202
    assert res.json()["queued"] == [evidence_id]
    status = client.get(f"/api/cases/{case_id}/evidence/{evidence_id}/processing").json()
    assert status["status"] == "completed"
    summary = client.get(f"/api/cases/{case_id}/processing").json()
    assert summary["items"][0]["extractor_available"] is True


def test_case_isolation_for_identical_workbooks(client):
    first, second = _make_case(client, "A"), _make_case(client, "B")
    filename, content, _ = SAMPLES["xlsx"]
    a = _post(client, first, filename, content).json()
    b = _post(client, second, filename, content).json()
    assert a["id"] != b["id"]
    assert client.get(f"/api/cases/{second}/evidence/{a['id']}").status_code == 404


# --- rejected -------------------------------------------------------------------

_BOMB = make_workbook_like_zip({"xl/worksheets/sheet1.xml": b"\x00" * (5 * MB)})
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600

REJECTED = [
    ("renamed.xlsx", PNG_BYTES, "png-as-xlsx"),
    ("renamed.xlsx", CSV_BYTES, "csv-as-xlsx"),
    ("renamed.xlsx", make_eml_bytes(), "eml-as-xlsx"),
    ("protected.xlsx", _OLE, "ole-workbook"),
    (
        "notbook.xlsx",
        make_workbook_like_zip().replace(b"xl/workbook.xml", b"xl/Workbook.xml"),
        "zip-without-workbook",
    ),
    ("bomb.xlsx", _BOMB, "expansion-bomb"),
    ("cut.xlsx", make_xlsx_bytes()[:1500], "truncated"),
    ("renamed.eml", PNG_BYTES, "png-as-eml"),
    ("renamed.eml", make_xlsx_bytes(), "xlsx-as-eml"),
    ("prose.eml", b"This is a note, not an email message.\n", "prose-as-eml"),
    ("table.eml", CSV_BYTES, "csv-as-eml"),
]


@pytest.mark.parametrize(
    "filename,content",
    [(f, c) for f, c, _ in REJECTED],
    ids=[i for _, _, i in REJECTED],
)
def test_invalid_uploads_are_rejected_before_storage(client, tmp_path, filename, content):
    case_id = _make_case(client)

    res = _post(client, case_id, filename, content)

    assert res.status_code == 400, res.text
    assert client.get(f"/api/cases/{case_id}/evidence").json()["total"] == 0
    assert _stored_files(tmp_path) == []


def test_ole_workbook_message_explains_what_to_do(client):
    case_id = _make_case(client)
    detail = _post(client, case_id, "protected.xlsx", _OLE).json()["detail"]
    assert "password" in detail
    assert ".xlsx" in detail


# --- limits enforced by the service ---------------------------------------------


def _service(db_session, storage, **env) -> EvidenceService:
    return EvidenceService(db_session, storage=storage, settings=Settings(**env))


def test_configured_zip_limits_apply_to_uploads(client, db_session, storage, tmp_path):
    case_id = uuid.UUID(_make_case(client))
    filename, content, _ = SAMPLES["xlsx"]

    service = _service(db_session, storage, MAX_ZIP_ENTRIES=3)
    with pytest.raises(BadRequestError, match="more than 3 entries"):
        service.upload(case_id, filename=filename, fileobj=io.BytesIO(content))
    assert _stored_files(tmp_path) == []


def test_default_settings_accept_the_sample_workbook(client, db_session, storage):
    case_id = uuid.UUID(_make_case(client))
    filename, content, _ = SAMPLES["xlsx"]
    evidence = _service(db_session, storage).upload(
        case_id, filename=filename, fileobj=io.BytesIO(content)
    )
    assert evidence.evidence_type == "tabular"


def test_upload_size_limit_still_applies_first(client, db_session, storage, tmp_path):
    assert Settings().max_upload_size_mb == 25  # the retained default
    case_id = uuid.UUID(_make_case(client))
    big = make_workbook_like_zip({"xl/worksheets/sheet1.xml": os.urandom(2 * MB)})

    service = _service(db_session, storage, MAX_UPLOAD_SIZE_MB=1)
    with pytest.raises(BadRequestError, match="maximum upload size"):
        service.upload(case_id, filename="big.xlsx", fileobj=io.BytesIO(big))
    assert _stored_files(tmp_path) == []
