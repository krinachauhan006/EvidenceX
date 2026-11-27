"""Integration tests for the evidence HTTP API against a real database + storage."""

from __future__ import annotations

import hashlib
import uuid

import pytest

from tests.fixtures.sample_files import SAMPLES


def _make_case(client, title="Evidence Case") -> str:
    res = client.post("/api/cases", json={"title": title, "description": None})
    assert res.status_code == 201
    return res.json()["id"]


def _upload(client, case_id, ext="pdf"):
    filename, content, _ = SAMPLES[ext]
    return client.post(
        f"/api/cases/{case_id}/evidence",
        files={"file": (filename, content, "application/octet-stream")},
    )


# --- upload: happy paths per modality ------------------------------------------


@pytest.mark.parametrize("ext", ["pdf", "png", "jpg", "jpeg", "webp", "wav", "mp3", "m4a"])
def test_upload_supported_file(client, ext):
    case_id = _make_case(client)
    filename, content, expected_type = SAMPLES[ext]

    res = _upload(client, case_id, ext)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["case_id"] == case_id
    assert body["original_filename"] == filename
    assert body["evidence_type"] == expected_type
    assert body["byte_size"] == len(content)
    assert body["sha256"] == hashlib.sha256(content).hexdigest()
    assert body["processing_status"] == "pending"
    assert body["processing_error"] is None
    # Storage path must never be exposed.
    assert "storage_path" not in body
    assert uuid.UUID(body["id"])


# --- upload: rejections ---------------------------------------------------------


def test_upload_to_missing_case_returns_404(client):
    res = _upload(client, str(uuid.uuid4()), "pdf")
    assert res.status_code == 404


def test_unsupported_extension_rejected(client):
    case_id = _make_case(client)
    res = client.post(
        f"/api/cases/{case_id}/evidence",
        files={"file": ("malware.exe", b"MZ\x90\x00\x03", "application/octet-stream")},
    )
    assert res.status_code == 400


def test_empty_file_rejected(client):
    case_id = _make_case(client)
    res = client.post(
        f"/api/cases/{case_id}/evidence",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert res.status_code == 400


def test_signature_mismatch_rejected(client):
    case_id = _make_case(client)
    # .pdf extension but PNG bytes.
    res = client.post(
        f"/api/cases/{case_id}/evidence",
        files={"file": ("fake.pdf", SAMPLES["png"][1], "application/pdf")},
    )
    assert res.status_code == 400


def test_oversized_file_rejected(client, settings, monkeypatch):
    case_id = _make_case(client)
    # The client's evidence service uses the per-test ``settings`` object.
    monkeypatch.setattr(settings, "max_upload_size_mb", 0, raising=False)
    # 0 MB limit -> any non-empty file is oversized.
    res = _upload(client, case_id, "pdf")
    assert res.status_code == 400


# --- listing --------------------------------------------------------------------


def test_list_empty(client):
    case_id = _make_case(client)
    res = client.get(f"/api/cases/{case_id}/evidence")
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_list_returns_case_evidence(client):
    case_id = _make_case(client)
    _upload(client, case_id, "pdf")
    _upload(client, case_id, "png")
    res = client.get(f"/api/cases/{case_id}/evidence")
    assert res.status_code == 200
    assert res.json()["total"] == 2


def test_list_missing_case_returns_404(client):
    res = client.get(f"/api/cases/{uuid.uuid4()}/evidence")
    assert res.status_code == 404


# --- metadata retrieval ---------------------------------------------------------


def test_get_metadata(client):
    case_id = _make_case(client)
    created = _upload(client, case_id, "pdf").json()
    res = client.get(f"/api/cases/{case_id}/evidence/{created['id']}")
    assert res.status_code == 200
    assert res.json()["id"] == created["id"]


def test_get_missing_evidence_returns_404(client):
    case_id = _make_case(client)
    res = client.get(f"/api/cases/{case_id}/evidence/{uuid.uuid4()}")
    assert res.status_code == 404


def test_get_malformed_id_returns_422(client):
    case_id = _make_case(client)
    res = client.get(f"/api/cases/{case_id}/evidence/not-a-uuid")
    assert res.status_code == 422


# --- download -------------------------------------------------------------------


def test_download_returns_original_bytes(client):
    case_id = _make_case(client)
    filename, content, _ = SAMPLES["pdf"]
    created = _upload(client, case_id, "pdf").json()
    res = client.get(f"/api/cases/{case_id}/evidence/{created['id']}/download")
    assert res.status_code == 200
    assert res.content == content
    assert "attachment" in res.headers["content-disposition"]
    assert filename in res.headers["content-disposition"]
    assert res.headers["x-content-type-options"] == "nosniff"


# --- deletion -------------------------------------------------------------------


def test_delete_evidence(client, storage):
    case_id = _make_case(client)
    created = _upload(client, case_id, "pdf").json()
    assert storage.exists(created["sha256"]) is True

    res = client.delete(f"/api/cases/{case_id}/evidence/{created['id']}")
    assert res.status_code == 204
    # Record gone.
    assert client.get(f"/api/cases/{case_id}/evidence/{created['id']}").status_code == 404
    # Blob removed (no other reference).
    assert storage.exists(created["sha256"]) is False


def test_delete_missing_evidence_returns_404(client):
    case_id = _make_case(client)
    res = client.delete(f"/api/cases/{case_id}/evidence/{uuid.uuid4()}")
    assert res.status_code == 404


def test_delete_keeps_shared_blob(client, storage):
    """Identical content in two cases shares one blob; deleting one keeps the blob."""
    case_a = _make_case(client, "A")
    case_b = _make_case(client, "B")
    ev_a = _upload(client, case_a, "png").json()
    ev_b = _upload(client, case_b, "png").json()
    assert ev_a["sha256"] == ev_b["sha256"]

    client.delete(f"/api/cases/{case_a}/evidence/{ev_a['id']}")
    # Still referenced by case B -> blob must remain.
    assert storage.exists(ev_a["sha256"]) is True


# --- case isolation -------------------------------------------------------------


def test_evidence_not_accessible_via_other_case(client):
    case_a = _make_case(client, "A")
    case_b = _make_case(client, "B")
    ev = _upload(client, case_a, "pdf").json()

    # Metadata, download, and delete must all 404 when scoped to the wrong case.
    assert client.get(f"/api/cases/{case_b}/evidence/{ev['id']}").status_code == 404
    assert client.get(f"/api/cases/{case_b}/evidence/{ev['id']}/download").status_code == 404
    assert client.delete(f"/api/cases/{case_b}/evidence/{ev['id']}").status_code == 404
    # And it is still intact under its real case.
    assert client.get(f"/api/cases/{case_a}/evidence/{ev['id']}").status_code == 200


def test_list_does_not_leak_across_cases(client):
    case_a = _make_case(client, "A")
    case_b = _make_case(client, "B")
    _upload(client, case_a, "pdf")

    res_b = client.get(f"/api/cases/{case_b}/evidence").json()
    assert res_b["total"] == 0


def test_deleting_case_cascades_evidence(client):
    case_id = _make_case(client)
    ev = _upload(client, case_id, "pdf").json()
    # Delete the owning case.
    assert client.delete(f"/api/cases/{case_id}").status_code == 204
    # The case is gone; listing its evidence now 404s (case not found).
    assert client.get(f"/api/cases/{case_id}/evidence").status_code == 404
    assert ev["id"]  # sanity


# --- storage failure handling ---------------------------------------------------


def test_missing_blob_download_returns_404(client, storage):
    case_id = _make_case(client)
    created = _upload(client, case_id, "pdf").json()
    # Simulate a storage failure: the blob vanishes from disk.
    storage.delete(created["sha256"])
    res = client.get(f"/api/cases/{case_id}/evidence/{created['id']}/download")
    assert res.status_code == 404
