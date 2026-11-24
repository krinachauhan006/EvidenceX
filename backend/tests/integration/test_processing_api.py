"""Integration tests for the processing API (CSV vertical slice).

The TestClient runs FastAPI background tasks before it returns, so after a
``process`` call the extraction has already happened and can be inspected.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.db_types import utcnow
from app.modules.evidence.models import Evidence
from app.modules.processing.errors import CorruptFileError
from app.modules.processing.extractors.csv_extractor import CsvExtractor
from app.modules.processing.models import Extraction, ExtractionSegment
from app.modules.processing.repository import ProcessingRepository
from tests.fixtures.fake_extractors import FailingExtractor, FlakyExtractor
from tests.fixtures.sample_files import CSV_BYTES, PDF_BYTES, PNG_BYTES

CSV_5_ROWS = b"n,label\n" + b"".join(f"{i},row{i}\n".encode() for i in range(1, 6))


# --- helpers --------------------------------------------------------------------


def make_case(client, title="Case") -> str:
    res = client.post("/api/cases", json={"title": title, "description": None})
    assert res.status_code == 201
    return res.json()["id"]


def upload(client, case_id, name="ledger.csv", data=CSV_BYTES):
    res = client.post(
        f"/api/cases/{case_id}/evidence",
        files={"file": (name, data, "application/octet-stream")},
    )
    assert res.status_code == 201, res.text
    return res.json()


def process(client, case_id, evidence_id, **body):
    return client.post(
        f"/api/cases/{case_id}/evidence/{evidence_id}/process", json=body or None
    )


def status_of(client, case_id, evidence_id) -> dict:
    res = client.get(f"/api/cases/{case_id}/evidence/{evidence_id}/processing")
    assert res.status_code == 200, res.text
    return res.json()


def segments_of(client, case_id, evidence_id, **params) -> dict:
    res = client.get(f"/api/cases/{case_id}/evidence/{evidence_id}/segments", params=params)
    assert res.status_code == 200, res.text
    return res.json()


def runs_of(client, case_id, evidence_id) -> list[dict]:
    res = client.get(f"/api/cases/{case_id}/evidence/{evidence_id}/extractions")
    assert res.status_code == 200, res.text
    return res.json()["items"]


# --- upload and basic flow ------------------------------------------------------


def test_csv_upload_is_accepted_and_not_processed(client, db_session):
    case_id = make_case(client)
    ev = upload(client, case_id)
    assert ev["evidence_type"] == "tabular"
    assert ev["mime_type"] == "text/csv"
    assert ev["processing_status"] == "pending"
    assert ev["processing_attempts"] == 0
    assert ev["sha256"] == hashlib.sha256(CSV_BYTES).hexdigest()
    # Upload must never extract.
    assert db_session.scalar(select(func.count()).select_from(Extraction)) == 0
    st = status_of(client, case_id, ev["id"])
    assert st["status"] == "pending"
    assert st["has_current_extraction"] is False
    base = f"/api/cases/{case_id}/evidence/{ev['id']}"
    assert client.get(f"{base}/extraction").status_code == 404
    assert client.get(f"{base}/segments").status_code == 404


def test_csv_upload_rejections(client):
    case_id = make_case(client)
    for name, data in [("fake.csv", PNG_BYTES), ("bin.csv", b"a,b\n1,\x00\x00\n")]:
        res = client.post(
            f"/api/cases/{case_id}/evidence", files={"file": (name, data, "text/csv")}
        )
        assert res.status_code == 400, name


def test_process_csv_end_to_end(client):
    case_id = make_case(client)
    ev = upload(client, case_id)

    res = process(client, case_id, ev["id"])
    assert res.status_code == 202
    assert res.json() == {"queued": [ev["id"]], "skipped": []}

    st = status_of(client, case_id, ev["id"])
    assert st["status"] == "completed"
    assert st["attempts"] == 1
    assert st["started_at"] and st["completed_at"]
    assert st["error"] is None and st["error_code"] is None
    assert st["has_current_extraction"] is True

    run = client.get(f"/api/cases/{case_id}/evidence/{ev['id']}/extraction").json()
    assert run["run_number"] == 1
    assert run["run_status"] == "completed"
    assert run["is_current"] is True
    assert run["extractor"] == "csv"
    assert run["outcome"] == "ok"
    assert run["source_sha256"] == ev["sha256"]
    assert run["segment_count"] == 3
    assert run["case_id"] == case_id and run["evidence_id"] == ev["id"]

    segs = segments_of(client, case_id, ev["id"])
    assert segs["total"] == 3
    assert [s["seq"] for s in segs["items"]] == [0, 1, 2]
    header, row2, row3 = segs["items"]
    assert header["segment_type"] == "table_header"
    assert row2["locator"] == {"kind": "csv", "row": 2, "line": 2, "column": None}
    assert row3["locator"]["row"] == 3
    assert {c["column"]: c["value"] for c in row2["data"]["cells"]} == {
        "date": "2026-10-12",
        "vendor": "Acme Ltd",
        "amount": "1200.50",
    }
    assert row2["page"] is None and row2["t_start"] is None

    # The existing evidence endpoints reflect the new state.
    listed = client.get(f"/api/cases/{case_id}/evidence").json()["items"][0]
    assert listed["processing_status"] == "completed"
    assert listed["processing_attempts"] == 1
    assert "storage_path" not in listed


def test_process_with_empty_body_and_with_force_false(client):
    case_id = make_case(client)
    ev = upload(client, case_id)
    assert client.post(f"/api/cases/{case_id}/evidence/{ev['id']}/process").status_code == 202
    assert status_of(client, case_id, ev["id"])["status"] == "completed"


def test_segment_pagination_and_filters(client):
    case_id = make_case(client)
    ev = upload(client, case_id, data=CSV_5_ROWS)
    process(client, case_id, ev["id"])

    page = segments_of(client, case_id, ev["id"], limit=2, offset=2)
    assert page["total"] == 6 and page["limit"] == 2 and page["offset"] == 2
    assert [s["seq"] for s in page["items"]] == [2, 3]

    rows_only = segments_of(client, case_id, ev["id"], segment_type="table_row")
    assert rows_only["total"] == 5
    base = f"/api/cases/{case_id}/evidence/{ev['id']}/segments"
    assert client.get(base, params={"limit": 0}).status_code == 422
    assert client.get(base, params={"limit": 501}).status_code == 422
    assert client.get(base, params={"page": 0}).status_code == 422


# --- idempotency and history ----------------------------------------------------


def test_processing_a_completed_item_again_is_a_noop(client):
    case_id = make_case(client)
    ev = upload(client, case_id)
    process(client, case_id, ev["id"])

    res = process(client, case_id, ev["id"])
    assert res.status_code == 202
    assert res.json() == {
        "queued": [],
        "skipped": [{"evidence_id": ev["id"], "reason": "already_completed"}],
    }
    assert status_of(client, case_id, ev["id"])["attempts"] == 1
    assert len(runs_of(client, case_id, ev["id"])) == 1


def test_force_adds_runs_and_preserves_full_history(client):
    case_id = make_case(client)
    ev = upload(client, case_id, data=CSV_5_ROWS)
    process(client, case_id, ev["id"])
    assert process(client, case_id, ev["id"], force=True).json()["queued"] == [ev["id"]]
    assert process(client, case_id, ev["id"], force=True).json()["queued"] == [ev["id"]]

    runs = runs_of(client, case_id, ev["id"])
    assert [r["run_number"] for r in runs] == [3, 2, 1]  # newest first
    assert [r["is_current"] for r in runs] == [True, False, False]
    assert all(r["run_status"] == "completed" and r["segment_count"] == 6 for r in runs)
    assert status_of(client, case_id, ev["id"])["attempts"] == 3

    # Every run keeps its own, readable segments. Nothing was rewritten or removed.
    seen_ids: set[str] = set()
    for run in runs:
        segs = segments_of(client, case_id, ev["id"], extraction_id=run["id"])
        assert segs["total"] == 6
        assert {s["extraction_id"] for s in segs["items"]} == {run["id"]}
        seen_ids.update(s["id"] for s in segs["items"])
    assert len(seen_ids) == 18  # 3 runs x 6 distinct segment rows

    # Without an id, the CURRENT run is served.
    default = segments_of(client, case_id, ev["id"])
    assert default["items"][0]["extraction_id"] == runs[0]["id"]

    old = client.get(f"/api/cases/{case_id}/evidence/{ev['id']}/extractions/{runs[2]['id']}")
    assert old.status_code == 200
    assert old.json()["is_current"] is False and old.json()["run_number"] == 1


def test_failed_forced_run_keeps_previous_run_current(client, registry):
    case_id = make_case(client)
    ev = upload(client, case_id)
    process(client, case_id, ev["id"])

    registry.register("text/csv", FailingExtractor(CorruptFileError("now it is broken")))
    process(client, case_id, ev["id"], force=True)

    st = status_of(client, case_id, ev["id"])
    assert st["status"] == "failed"
    assert st["error_code"] == "corrupt_file"
    assert st["has_current_extraction"] is True  # earlier results remain available
    assert st["current_extraction"]["run_number"] == 1

    runs = runs_of(client, case_id, ev["id"])
    failed, good = runs
    assert failed["run_number"] == 2 and failed["run_status"] == "failed"
    assert failed["is_current"] is False and failed["outcome"] is None
    assert failed["error_code"] == "corrupt_file" and failed["segment_count"] == 0
    assert good["run_number"] == 1 and good["is_current"] is True
    assert segments_of(client, case_id, ev["id"])["total"] == 3  # still the good run


# --- failure, retry, isolation ----------------------------------------------------


def test_failure_is_recorded_then_retry_succeeds(client, registry):
    case_id = make_case(client)
    ev = upload(client, case_id)
    registry.register(
        "text/csv", FlakyExtractor(CorruptFileError("first attempt fails"), CsvExtractor())
    )

    process(client, case_id, ev["id"])
    st = status_of(client, case_id, ev["id"])
    assert st["status"] == "failed"
    assert st["error"] == "first attempt fails"
    assert st["error_code"] == "corrupt_file"
    assert st["attempts"] == 1
    assert st["has_current_extraction"] is False
    base = f"/api/cases/{case_id}/evidence/{ev['id']}"
    assert client.get(f"{base}/extraction").status_code == 404

    res = client.post(f"{base}/retry")
    assert res.status_code == 202 and res.json()["queued"] == [ev["id"]]
    st = status_of(client, case_id, ev["id"])
    assert st["status"] == "completed" and st["attempts"] == 2
    assert st["error"] is None and st["error_code"] is None

    runs = runs_of(client, case_id, ev["id"])
    assert [(r["run_number"], r["run_status"], r["is_current"]) for r in runs] == [
        (2, "completed", True),
        (1, "failed", False),
    ]


def test_retry_only_for_failed_items(client):
    case_id = make_case(client)
    ev = upload(client, case_id)
    base = f"/api/cases/{case_id}/evidence/{ev['id']}"
    assert client.post(f"{base}/retry").status_code == 409  # pending
    process(client, case_id, ev["id"])
    assert client.post(f"{base}/retry").status_code == 409  # completed


def test_one_failure_does_not_stop_the_batch(client, registry):
    case_id = make_case(client)
    good_a = upload(client, case_id, "a.csv", CSV_BYTES)
    broken = upload(client, case_id, "broken.pdf", PDF_BYTES)
    good_b = upload(client, case_id, "b.csv", CSV_5_ROWS)
    registry.register("application/pdf", FailingExtractor(CorruptFileError("bad pdf")))

    res = client.post(f"/api/cases/{case_id}/evidence/process-pending")
    assert res.status_code == 202
    assert set(res.json()["queued"]) == {good_a["id"], broken["id"], good_b["id"]}

    assert status_of(client, case_id, good_a["id"])["status"] == "completed"
    assert status_of(client, case_id, good_b["id"])["status"] == "completed"
    bad = status_of(client, case_id, broken["id"])
    assert bad["status"] == "failed" and bad["error_code"] == "corrupt_file"
    # The failed item left no segments behind.
    assert client.get(f"/api/cases/{case_id}/evidence/{broken['id']}/segments").status_code == 404
    assert runs_of(client, case_id, broken["id"])[0]["segment_count"] == 0

    summary = client.get(f"/api/cases/{case_id}/processing").json()
    assert summary["counts"] == {
        "total": 3, "pending": 0, "processing": 0, "completed": 2, "failed": 1,
    }


def test_unexpected_crash_is_isolated_and_message_is_generic(client, registry, caplog):
    case_id = make_case(client)
    ev = upload(client, case_id)
    registry.register(
        "text/csv", FailingExtractor(RuntimeError("SECRET-FILE-CONTENT leaked in message"))
    )
    with caplog.at_level(logging.DEBUG):
        process(client, case_id, ev["id"])

    st = status_of(client, case_id, ev["id"])
    assert st["status"] == "failed"
    assert st["error_code"] == "internal_error"
    assert "SECRET-FILE-CONTENT" not in (st["error"] or "")
    assert "SECRET-FILE-CONTENT" not in caplog.text  # exception messages are not logged


def test_logs_never_contain_extracted_text(client, caplog):
    case_id = make_case(client)
    ev = upload(client, case_id, data=b"name,note\nalpha,TOP-SECRET-NOTE\n")
    with caplog.at_level(logging.DEBUG):
        process(client, case_id, ev["id"])
    assert status_of(client, case_id, ev["id"])["status"] == "completed"
    assert "TOP-SECRET-NOTE" not in caplog.text


def test_missing_blob_fails_with_storage_missing(client, storage):
    case_id = make_case(client)
    ev = upload(client, case_id)
    storage.delete(ev["sha256"])
    process(client, case_id, ev["id"])
    st = status_of(client, case_id, ev["id"])
    assert st["status"] == "failed" and st["error_code"] == "storage_missing"


# --- which items get queued -------------------------------------------------------


def test_items_without_an_extractor_stay_pending(client, registry):
    # Every upload format now has an extractor, so remove PNG's to model "a type with
    # no extractor in the running build" (for example PDF with PDF_EXTRACTION_ENABLED off).
    registry.unregister("image/png")
    case_id = make_case(client)
    csv_ev = upload(client, case_id)
    png_ev = upload(client, case_id, "scan.png", PNG_BYTES)

    res = client.post(f"/api/cases/{case_id}/evidence/process-pending")
    assert res.status_code == 202
    assert res.json() == {
        "queued": [csv_ev["id"]],
        "skipped": [{"evidence_id": png_ev["id"], "reason": "no_extractor"}],
    }
    assert status_of(client, case_id, png_ev["id"])["status"] == "pending"

    single = process(client, case_id, png_ev["id"])
    assert single.json()["skipped"][0]["reason"] == "no_extractor"
    assert status_of(client, case_id, png_ev["id"])["status"] == "pending"


def test_process_pending_does_not_retry_failed_items(client, registry):
    case_id = make_case(client)
    ev = upload(client, case_id)
    registry.register("text/csv", FailingExtractor(CorruptFileError("nope")))
    process(client, case_id, ev["id"])
    assert status_of(client, case_id, ev["id"])["status"] == "failed"

    res = client.post(f"/api/cases/{case_id}/evidence/process-pending")
    assert res.json() == {"queued": [], "skipped": []}
    assert status_of(client, case_id, ev["id"])["attempts"] == 1


def test_case_summary(client, registry):
    registry.unregister("image/png")  # see test_items_without_an_extractor_stay_pending
    case_id = make_case(client)
    done = upload(client, case_id, "a.csv", CSV_BYTES)
    waiting = upload(client, case_id, "scan.png", PNG_BYTES)
    process(client, case_id, done["id"])

    summary = client.get(f"/api/cases/{case_id}/processing").json()
    assert summary["counts"] == {
        "total": 2, "pending": 1, "processing": 0, "completed": 1, "failed": 0,
    }
    by_id = {i["evidence_id"]: i for i in summary["items"]}
    assert by_id[done["id"]]["outcome"] == "ok"
    assert by_id[done["id"]]["segment_count"] == 3
    assert by_id[done["id"]]["run_number"] == 1
    assert by_id[done["id"]]["extractor_available"] is True
    assert by_id[waiting["id"]]["outcome"] is None
    assert by_id[waiting["id"]]["extractor_available"] is False


# --- claim / state machine --------------------------------------------------------


def test_claim_is_atomic_and_idempotent(client, db_session):
    case_id = make_case(client)
    ev = upload(client, case_id)
    repo = ProcessingRepository(db_session)
    now = utcnow()
    cutoff = now - timedelta(minutes=30)
    cid, eid = uuid.UUID(case_id), uuid.UUID(ev["id"])

    assert repo.claim(cid, eid, force=False, now=now, stale_cutoff=cutoff) is True
    # The loser of a race sees the item as already processing.
    assert repo.claim(cid, eid, force=False, now=now, stale_cutoff=cutoff) is False
    assert repo.get_evidence(cid, eid).processing_attempts == 1


def test_stale_processing_items_can_be_reclaimed(client, db_session):
    case_id = make_case(client)
    ev = upload(client, case_id)
    cid, eid = uuid.UUID(case_id), uuid.UUID(ev["id"])
    repo = ProcessingRepository(db_session)
    now = utcnow()
    cutoff = now - timedelta(minutes=30)

    row = db_session.get(Evidence, eid)
    row.processing_status = "processing"
    row.processing_started_at = now - timedelta(minutes=1)
    row.processing_attempts = 1
    db_session.commit()

    # Fresh: still considered running, by the claim and by the request-side check.
    assert process(client, case_id, ev["id"]).json()["skipped"][0]["reason"] == "already_processing"
    assert repo.claim(cid, eid, force=False, now=now, stale_cutoff=cutoff) is False

    # Abandoned: older than the stale window, so it can be taken over.
    row.processing_started_at = now - timedelta(minutes=90)
    db_session.commit()
    res = process(client, case_id, ev["id"])
    assert res.json()["queued"] == [ev["id"]]
    st = status_of(client, case_id, ev["id"])
    assert st["status"] == "completed" and st["attempts"] == 2


def test_runner_skips_when_not_eligible(runner, client):
    case_id = make_case(client)
    ev = upload(client, case_id)
    cid, eid = uuid.UUID(case_id), uuid.UUID(ev["id"])
    assert runner.run_one(cid, eid) == "completed"
    assert runner.run_one(cid, eid) == "skipped"  # completed, no force
    assert runner.run_one(cid, eid, force=True) == "completed"
    assert runner.run_one(cid, uuid.uuid4()) == "skipped"  # unknown id


# --- case isolation ---------------------------------------------------------------


def test_case_isolation_on_every_endpoint(client):
    case_a = make_case(client, "A")
    case_b = make_case(client, "B")
    ev = upload(client, case_a)
    process(client, case_a, ev["id"])
    run_id = runs_of(client, case_a, ev["id"])[0]["id"]

    base = f"/api/cases/{case_b}/evidence/{ev['id']}"
    assert client.post(f"{base}/process").status_code == 404
    assert client.post(f"{base}/retry").status_code == 404
    assert client.get(f"{base}/processing").status_code == 404
    assert client.get(f"{base}/extraction").status_code == 404
    assert client.get(f"{base}/extractions").status_code == 404
    assert client.get(f"{base}/extractions/{run_id}").status_code == 404
    assert client.get(f"{base}/segments").status_code == 404
    assert client.get(f"{base}/segments", params={"extraction_id": run_id}).status_code == 404
    # ...and everything still works under the owning case.
    assert segments_of(client, case_a, ev["id"])["total"] == 3


def test_case_b_cannot_read_a_run_through_its_own_evidence(client):
    case_a = make_case(client, "A")
    case_b = make_case(client, "B")
    ev_a = upload(client, case_a)
    ev_b = upload(client, case_b)
    process(client, case_a, ev_a["id"])
    process(client, case_b, ev_b["id"])
    run_a = runs_of(client, case_a, ev_a["id"])[0]["id"]
    # B's evidence id with A's extraction id must not return A's run or segments.
    own = f"/api/cases/{case_b}/evidence/{ev_b['id']}"
    assert client.get(f"{own}/extractions/{run_a}").status_code == 404
    assert client.get(f"{own}/segments", params={"extraction_id": run_a}).status_code == 404


def test_process_pending_is_scoped_to_its_case(client):
    case_a = make_case(client, "A")
    case_b = make_case(client, "B")
    ev_a = upload(client, case_a)

    res = client.post(f"/api/cases/{case_b}/evidence/process-pending")
    assert res.json() == {"queued": [], "skipped": []}
    assert status_of(client, case_a, ev_a["id"])["status"] == "pending"


def test_identical_content_in_two_cases_gives_independent_extractions(client):
    case_a = make_case(client, "A")
    case_b = make_case(client, "B")
    ev_a = upload(client, case_a)
    ev_b = upload(client, case_b)
    assert ev_a["sha256"] == ev_b["sha256"]
    process(client, case_a, ev_a["id"])
    process(client, case_b, ev_b["id"])
    run_a = runs_of(client, case_a, ev_a["id"])[0]
    run_b = runs_of(client, case_b, ev_b["id"])[0]
    assert run_a["id"] != run_b["id"]
    assert run_a["case_id"] == case_a and run_b["case_id"] == case_b
    seg_ids_a = {s["id"] for s in segments_of(client, case_a, ev_a["id"])["items"]}
    seg_ids_b = {s["id"] for s in segments_of(client, case_b, ev_b["id"])["items"]}
    assert seg_ids_a.isdisjoint(seg_ids_b)


def test_unknown_case_and_malformed_ids(client):
    ghost = uuid.uuid4()
    assert client.post(f"/api/cases/{ghost}/evidence/process-pending").status_code == 404
    assert client.get(f"/api/cases/{ghost}/processing").status_code == 404
    case_id = make_case(client)
    assert client.post(f"/api/cases/{case_id}/evidence/not-a-uuid/process").status_code == 422
    assert process(client, case_id, str(uuid.uuid4())).status_code == 404


# --- cascade ----------------------------------------------------------------------


def _counts(db):
    return (
        db.scalar(select(func.count()).select_from(Extraction)),
        db.scalar(select(func.count()).select_from(ExtractionSegment)),
    )


def test_deleting_evidence_removes_its_whole_history(client, db_session):
    case_id = make_case(client)
    keep = upload(client, case_id, "keep.csv", CSV_BYTES)
    drop = upload(client, case_id, "drop.csv", CSV_5_ROWS)
    process(client, case_id, keep["id"])
    process(client, case_id, drop["id"])
    process(client, case_id, drop["id"], force=True)
    assert _counts(db_session) == (3, 3 + 6 + 6)

    assert client.delete(f"/api/cases/{case_id}/evidence/{drop['id']}").status_code == 204
    # Only the untouched item's history remains.
    assert _counts(db_session) == (1, 3)
    assert segments_of(client, case_id, keep["id"])["total"] == 3


def test_deleting_a_case_removes_its_extractions(client, db_session):
    case_id = make_case(client)
    other = make_case(client, "other")
    ev = upload(client, case_id)
    other_ev = upload(client, other)
    process(client, case_id, ev["id"])
    process(client, other, other_ev["id"])
    assert _counts(db_session) == (2, 6)

    assert client.delete(f"/api/cases/{case_id}").status_code == 204
    assert _counts(db_session) == (1, 3)
    assert segments_of(client, other, other_ev["id"])["total"] == 3


# --- regression: route shadowing --------------------------------------------------


def test_process_pending_route_is_not_shadowed_by_evidence_routes(client):
    case_id = make_case(client)
    res = client.post(f"/api/cases/{case_id}/evidence/process-pending")
    assert res.status_code == 202  # not 405 (method) and not 422 (uuid parse)


@pytest.mark.parametrize("path", ["/health"])
def test_existing_routes_still_work(client, path):
    assert client.get(path).status_code == 200
