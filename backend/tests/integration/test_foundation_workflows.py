"""Foundation MVP: complete workflows through the HTTP API.

Every test runs against an isolated in-memory database and a temporary blob store.
Nothing touches ``var/evidencex.db`` or ``var/storage``.
"""

from __future__ import annotations

import io
import uuid

import pytest

from app.modules.evidence.service import EvidenceService
from app.modules.processing.extractors.audio import AudioExtractor
from app.modules.processing.extractors.image_ocr import ImageOcrExtractor
from tests.fixtures.fake_engines import FakeOcrEngine, FakeTranscriber
from tests.fixtures.processing_samples import (
    make_eml_bytes,
    make_pdf_text,
    make_text_png,
    make_wav,
    make_workbook_like_zip,
    make_xlsx_bytes,
)
from tests.fixtures.sample_files import CSV_BYTES, SAMPLES

# --- helpers --------------------------------------------------------------------


def make_case(client, title="Workflow case", description=None) -> str:
    res = client.post("/api/cases", json={"title": title, "description": description})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def upload(client, case_id, name, content):
    return client.post(
        f"/api/cases/{case_id}/evidence",
        files={"file": (name, content, "application/octet-stream")},
    )


def uploaded(client, case_id, name, content) -> dict:
    res = upload(client, case_id, name, content)
    assert res.status_code == 201, res.text
    return res.json()


def base(case_id, evidence_id) -> str:
    return f"/api/cases/{case_id}/evidence/{evidence_id}"


def process(client, case_id, evidence_id, force=False):
    return client.post(f"{base(case_id, evidence_id)}/process", json={"force": force})


def status_of(client, case_id, evidence_id) -> dict:
    return client.get(f"{base(case_id, evidence_id)}/processing").json()


def segments_of(client, case_id, evidence_id, extraction_id=None) -> list[dict]:
    suffix = f"&extraction_id={extraction_id}" if extraction_id else ""
    res = client.get(f"{base(case_id, evidence_id)}/segments?limit=500{suffix}")
    assert res.status_code == 200, res.text
    return res.json()["items"]


def runs_of(client, case_id, evidence_id) -> list[dict]:
    return client.get(f"{base(case_id, evidence_id)}/extractions").json()["items"]


def blob_names(storage) -> list[str]:
    root = storage._root
    return sorted(p.name for p in root.rglob("*") if p.is_file())


def assert_storage_clean(storage) -> None:
    """Only content-addressed blobs: no .part, .hold or temporary files."""
    import re

    assert all(re.fullmatch(r"[0-9a-f]{64}", n) for n in blob_names(storage)), blob_names(storage)


@pytest.fixture(autouse=True)
def fake_engines(registry):
    registry.register("image/png", ImageOcrExtractor(FakeOcrEngine()))
    registry.register("image/jpeg", ImageOcrExtractor(FakeOcrEngine()))
    registry.register("image/webp", ImageOcrExtractor(FakeOcrEngine()))
    for mime in ("audio/wav", "audio/mpeg", "audio/mp4"):
        registry.register(mime, AudioExtractor(FakeTranscriber()))


# --- workflow 1: case lifecycle -------------------------------------------------


def test_workflow_case_lifecycle(client):
    case_id = make_case(client, "Disposable case", "first description")

    opened = client.get(f"/api/cases/{case_id}").json()
    assert opened["title"] == "Disposable case" and opened["status"] == "open"

    edited = client.patch(
        f"/api/cases/{case_id}", json={"title": "Edited case", "description": "second"}
    ).json()
    assert (edited["title"], edited["description"]) == ("Edited case", "second")

    archived = client.post(f"/api/cases/{case_id}/archive").json()
    assert archived["status"] == "archived"
    open_ids = [c["id"] for c in client.get("/api/cases?status=open").json()["items"]]
    archived_ids = [c["id"] for c in client.get("/api/cases?status=archived").json()["items"]]
    assert case_id not in open_ids and case_id in archived_ids

    restored = client.patch(f"/api/cases/{case_id}", json={"status": "open"}).json()
    assert restored["status"] == "open"
    open_ids = [c["id"] for c in client.get("/api/cases?status=open").json()["items"]]
    assert case_id in open_ids

    assert client.delete(f"/api/cases/{case_id}").status_code == 204
    assert client.get(f"/api/cases/{case_id}").status_code == 404
    assert client.delete(f"/api/cases/{case_id}").status_code == 404


def test_workflow_deleting_a_case_removes_its_evidence_runs_and_blobs(client, storage, db_session):
    case_id = make_case(client)
    ev = uploaded(client, case_id, "book.xlsx", make_xlsx_bytes())
    process(client, case_id, ev["id"])
    assert storage.exists(ev["sha256"])

    # The case-delete route cleans blobs through the application's configured storage,
    # not this test's temporary one, so run the same cleanup step against the temporary
    # store, then delete through the API (database rows go by cascade).
    EvidenceService(db_session, storage=storage).cleanup_case_blobs(uuid.UUID(case_id))
    assert not storage.exists(ev["sha256"])
    assert client.delete(f"/api/cases/{case_id}").status_code == 204
    assert client.get(f"{base(case_id, ev['id'])}/extractions").status_code == 404
    assert client.get(f"{base(case_id, ev['id'])}/segments").status_code == 404
    assert_storage_clean(storage)


# --- workflow 2: evidence lifecycle ---------------------------------------------


@pytest.mark.parametrize("ext", sorted(SAMPLES))
def test_workflow_evidence_lifecycle_for_every_format(client, storage, ext):
    filename, content, expected_type = SAMPLES[ext]
    case_id = make_case(client)

    ev = uploaded(client, case_id, filename, content)
    assert ev["evidence_type"] == expected_type and ev["processing_status"] == "pending"
    assert storage.exists(ev["sha256"])

    assert client.get(base(case_id, ev["id"])).json()["sha256"] == ev["sha256"]
    download = client.get(f"{base(case_id, ev['id'])}/download")
    assert download.status_code == 200 and download.content == content
    assert "attachment" in download.headers["content-disposition"]
    assert download.headers.get("x-content-type-options") == "nosniff"

    assert client.delete(base(case_id, ev["id"])).status_code == 204
    assert client.get(base(case_id, ev["id"])).status_code == 404
    assert not storage.exists(ev["sha256"])
    assert_storage_clean(storage)


def test_workflow_duplicate_content_shares_one_blob_until_the_last_reference_goes(client, storage):
    first_case, second_case = make_case(client, "A"), make_case(client, "B")
    a = uploaded(client, first_case, "ledger.csv", CSV_BYTES)
    b = uploaded(client, second_case, "copy-of-ledger.csv", CSV_BYTES)
    assert a["sha256"] == b["sha256"] and a["id"] != b["id"]
    assert len(blob_names(storage)) == 1

    assert client.delete(base(first_case, a["id"])).status_code == 204
    assert storage.exists(a["sha256"])  # still referenced by the other case
    assert client.get(f"{base(second_case, b['id'])}/download").content == CSV_BYTES

    assert client.delete(base(second_case, b["id"])).status_code == 204
    assert not storage.exists(a["sha256"])


def test_workflow_unsafe_filenames_never_reach_storage_paths(client, storage):
    case_id = make_case(client)
    ev = uploaded(client, case_id, "..\\..\\evil name.csv", CSV_BYTES)
    assert ev["original_filename"].endswith("evil name.csv")
    assert_storage_clean(storage)
    assert "storage_path" not in ev


# --- workflow 3: processing -----------------------------------------------------


def test_workflow_process_read_reprocess_keeps_history(client):
    case_id = make_case(client)
    ev = uploaded(client, case_id, "book.xlsx", make_xlsx_bytes())

    assert process(client, case_id, ev["id"]).json()["queued"] == [ev["id"]]
    assert status_of(client, case_id, ev["id"])["status"] == "completed"
    run1 = client.get(f"{base(case_id, ev['id'])}/extraction").json()
    assert run1["run_number"] == 1 and run1["is_current"] and run1["outcome"] == "ok"
    first = segments_of(client, case_id, ev["id"])
    assert {s["locator"]["kind"] for s in first} == {"xlsx"}
    row = next(s for s in first if s["locator"]["sheet"] == "Payments" and s["locator"]["row"] == 2)
    assert row["locator"]["range"] == "A2:E2"
    assert {c["coord"] for c in row["data"]["cells"]} == {"A2", "B2", "C2", "D2", "E2"}

    skipped = process(client, case_id, ev["id"]).json()
    assert skipped["skipped"] == [{"evidence_id": ev["id"], "reason": "already_completed"}]
    assert len(runs_of(client, case_id, ev["id"])) == 1

    assert process(client, case_id, ev["id"], force=True).json()["queued"] == [ev["id"]]
    runs = runs_of(client, case_id, ev["id"])
    assert [r["run_number"] for r in runs] == [2, 1]  # newest first
    assert [r["is_current"] for r in runs] == [True, False]
    old = segments_of(client, case_id, ev["id"], run1["id"])
    new = segments_of(client, case_id, ev["id"])
    assert [s["text"] for s in old] == [s["text"] for s in new]
    assert {s["id"] for s in old}.isdisjoint({s["id"] for s in new})
    assert [s["id"] for s in old] == [s["id"] for s in first]  # run 1 unchanged


def test_workflow_every_segment_has_a_valid_locator(client):
    case_id = make_case(client)
    for name, content in [
        ("ledger.csv", CSV_BYTES),
        ("book.xlsx", make_xlsx_bytes()),
        ("mail.eml", make_eml_bytes()),
        ("report.pdf", make_pdf_text(2)),
        ("scan.png", make_text_png()),
        ("call.wav", make_wav(0.5)),
    ]:
        ev = uploaded(client, case_id, name, content)
        process(client, case_id, ev["id"])
        assert status_of(client, case_id, ev["id"])["status"] == "completed", name
        segments = segments_of(client, case_id, ev["id"])
        assert segments, name
        assert all(s["locator"]["kind"] for s in segments), name


# --- workflow 4: failure and recovery -------------------------------------------


def test_workflow_missing_blob_fails_safely_then_recovers(client, storage):
    case_id = make_case(client)
    content = make_xlsx_bytes()
    ev = uploaded(client, case_id, "book.xlsx", content)
    process(client, case_id, ev["id"])
    run1 = client.get(f"{base(case_id, ev['id'])}/extraction").json()
    run1_segments = segments_of(client, case_id, ev["id"])

    storage.delete(ev["sha256"])  # simulate a lost blob (temporary test storage)
    process(client, case_id, ev["id"], force=True)
    failed = status_of(client, case_id, ev["id"])
    assert failed["status"] == "failed" and failed["error_code"] == "storage_missing"
    assert failed["has_current_extraction"] and failed["current_extraction"]["id"] == run1["id"]
    assert segments_of(client, case_id, ev["id"]) == run1_segments
    run2 = next(r for r in runs_of(client, case_id, ev["id"]) if r["run_number"] == 2)
    assert run2["run_status"] == "failed" and run2["segment_count"] == 0
    assert segments_of(client, case_id, ev["id"], run2["id"]) == []

    storage.put_stream(io.BytesIO(content))  # restore the blob
    assert client.post(f"{base(case_id, ev['id'])}/retry").json()["queued"] == [ev["id"]]
    recovered = status_of(client, case_id, ev["id"])
    assert recovered["status"] == "completed" and recovered["error_code"] is None
    runs = {r["run_number"]: r for r in runs_of(client, case_id, ev["id"])}
    assert runs[3]["is_current"] and not runs[1]["is_current"] and not runs[2]["is_current"]
    assert runs[1]["run_status"] == "completed" and runs[2]["run_status"] == "failed"
    assert segments_of(client, case_id, ev["id"], run1["id"]) == run1_segments
    assert_storage_clean(storage)


def test_workflow_corrupt_file_fails_with_a_reason_and_can_be_retried(client):
    case_id = make_case(client)
    # Passes upload validation (a ZIP with the workbook parts) but is not a real workbook.
    ev = uploaded(client, case_id, "broken.xlsx", make_workbook_like_zip())
    process(client, case_id, ev["id"])
    state = status_of(client, case_id, ev["id"])
    assert state["status"] == "failed" and state["error_code"] == "corrupt_file"
    assert not state["has_current_extraction"]
    assert client.post(f"{base(case_id, ev['id'])}/retry").status_code == 202
    assert status_of(client, case_id, ev["id"])["attempts"] == 2
    assert client.post(f"{base(case_id, ev['id'])}/retry").status_code == 202  # still failed


def test_workflow_retry_is_refused_for_items_that_are_not_failed(client):
    case_id = make_case(client)
    ev = uploaded(client, case_id, "ledger.csv", CSV_BYTES)
    assert client.post(f"{base(case_id, ev['id'])}/retry").status_code == 409
    process(client, case_id, ev["id"])
    assert client.post(f"{base(case_id, ev['id'])}/retry").status_code == 409


# --- workflow 5: mixed formats --------------------------------------------------


def test_workflow_mixed_formats_in_one_case_with_one_failure(client, storage):
    case_id = make_case(client)
    files = {
        "ledger.csv": ("csv", CSV_BYTES),
        "book.xlsx": ("xlsx", make_xlsx_bytes()),
        "mail.eml": ("email", make_eml_bytes()),
        "report.pdf": ("pdf", make_pdf_text(2)),
        "scan.png": ("image", make_text_png()),
        "call.wav": ("audio", make_wav(0.5)),
        "broken.xlsx": (None, make_workbook_like_zip()),
    }
    ids = {name: uploaded(client, case_id, name, data)["id"] for name, (_, data) in files.items()}

    res = client.post(f"/api/cases/{case_id}/evidence/process-pending")
    assert res.status_code == 202
    assert sorted(res.json()["queued"]) == sorted(ids.values()) and res.json()["skipped"] == []

    summary = client.get(f"/api/cases/{case_id}/processing").json()
    assert summary["counts"] == {
        "total": 7,
        "pending": 0,
        "processing": 0,
        "completed": 6,
        "failed": 1,
    }
    by_name = {i["original_filename"]: i for i in summary["items"]}
    assert by_name["broken.xlsx"]["status"] == "failed"
    assert by_name["broken.xlsx"]["error_code"] == "corrupt_file"

    expected_kind = {
        "ledger.csv": "csv",
        "book.xlsx": "xlsx",
        "mail.eml": "email",
        "report.pdf": "pdf",
        "scan.png": "image",
        "call.wav": "audio",
    }
    for name, kind in expected_kind.items():
        assert by_name[name]["status"] == "completed", name
        segments = segments_of(client, case_id, ids[name])
        assert segments and {s["locator"]["kind"] for s in segments} == {kind}, name
        run = client.get(f"{base(case_id, ids[name])}/extraction").json()
        assert run["evidence_id"] == ids[name] and run["case_id"] == case_id
        assert all(s["extraction_id"] == run["id"] for s in segments)
    assert_storage_clean(storage)


# --- workflow 6: isolation ------------------------------------------------------


def test_workflow_cases_cannot_reach_each_others_evidence(client, storage):
    owner, other = make_case(client, "Owner"), make_case(client, "Other")
    ev = uploaded(client, owner, "book.xlsx", make_xlsx_bytes())
    process(client, owner, ev["id"])
    run = client.get(f"{base(owner, ev['id'])}/extraction").json()
    bystander = uploaded(client, other, "ledger.csv", CSV_BYTES)

    wrong = base(other, ev["id"])
    for path in (
        wrong,
        f"{wrong}/download",
        f"{wrong}/processing",
        f"{wrong}/extraction",
        f"{wrong}/extractions",
        f"{wrong}/extractions/{run['id']}",
        f"{wrong}/segments",
    ):
        assert client.get(path).status_code == 404, path
    assert client.post(f"{wrong}/process", json={"force": True}).status_code == 404
    assert client.post(f"{wrong}/retry").status_code == 404
    assert client.delete(wrong).status_code == 404

    # Still intact for the owner.
    assert client.get(base(owner, ev["id"])).status_code == 200
    assert storage.exists(ev["sha256"])
    assert len(runs_of(client, owner, ev["id"])) == 1

    # Processing the other case never touches the owner's evidence.
    client.post(f"/api/cases/{other}/evidence/process-pending")
    assert status_of(client, other, bystander["id"])["status"] == "completed"
    assert len(runs_of(client, owner, ev["id"])) == 1
    assert client.get(f"/api/cases/{other}/processing").json()["counts"]["total"] == 1


def test_workflow_identical_content_in_two_cases_has_independent_extractions(client):
    first, second = make_case(client, "A"), make_case(client, "B")
    a = uploaded(client, first, "ledger.csv", CSV_BYTES)
    b = uploaded(client, second, "ledger.csv", CSV_BYTES)
    process(client, first, a["id"])
    assert status_of(client, second, b["id"])["status"] == "pending"
    process(client, second, b["id"])
    seg_a, seg_b = segments_of(client, first, a["id"]), segments_of(client, second, b["id"])
    assert [s["text"] for s in seg_a] == [s["text"] for s in seg_b]
    assert {s["id"] for s in seg_a}.isdisjoint({s["id"] for s in seg_b})


def test_workflow_unknown_ids_return_404_not_500(client):
    case_id = make_case(client)
    ghost = str(uuid.uuid4())
    assert client.get(f"{base(case_id, ghost)}/processing").status_code == 404
    assert client.post(f"{base(case_id, ghost)}/process", json={}).status_code == 404
    assert client.get(f"/api/cases/{ghost}/processing").status_code == 404
