"""Failure, retry and recovery through the real HTTP API and the real runner.

Failures here are genuine: the production runner hits a real problem and records a
real ``failed`` run in the database. Nothing is faked at the extractor level.

- Transient failure: the stored blob is temporarily hidden (``storage_missing``),
  then restored, so a retry can succeed.
- Permanent failure: a CSV that passes upload validation but cannot be decoded
  (``corrupt_file`` from the real CSV extractor).

Everything runs on the isolated in-memory database and a per-test temporary storage
folder supplied by ``conftest.py``.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.modules.processing.models import Extraction
from tests.fixtures import processing_api as api
from tests.fixtures.blob_control import hidden_blob

MISSING_MESSAGE = "The stored file is missing."
CORRUPT_UTF16_MESSAGE = "The file declares UTF-16 but could not be decoded."

# Valid enough to pass upload validation (a UTF-16 byte-order mark is accepted), but
# the decoder rejects them.
CORRUPT_UTF16 = {
    "odd_length": b"\xff\xfe\x61\x00\x62",
    "unpaired_surrogate": b"\xff\xfe\x00\xd8\x41\x00",
}


def current_flags(db_session, evidence_id: str) -> list[bool]:
    rows = db_session.scalars(
        select(Extraction.is_current).where(Extraction.evidence_id == uuid.UUID(evidence_id))
    ).all()
    return list(rows)


# --- forced re-run fails, retry recovers, history preserved --------------------------


def test_forced_failure_then_retry_recovers_and_preserves_history(client, storage, db_session):
    case_id = api.make_case(client)
    ev = api.upload(client, case_id, api.unique_csv(3))
    eid, sha = ev["id"], ev["sha256"]

    # Run 1 succeeds.
    assert api.process(client, case_id, eid).status_code == 202
    assert api.status(client, case_id, eid)["status"] == "completed"
    run1 = api.runs(client, case_id, eid)[0]
    run1_segments = api.segments(client, case_id, eid)
    assert len(run1_segments) == 4  # header + 3 rows
    assert {s["extraction_id"] for s in run1_segments} == {run1["id"]}

    # Run 2: a forced re-process while the stored file is unavailable.
    with hidden_blob(storage, sha):
        res = api.process(client, case_id, eid, force=True)
        assert res.status_code == 202
        assert res.json() == {"queued": [eid], "skipped": []}

        # What the UI polls: the status endpoint.
        st = api.status(client, case_id, eid)
        assert st["status"] == "failed"
        assert st["error_code"] == "storage_missing"
        assert st["error"] == MISSING_MESSAGE
        assert st["attempts"] == 2
        assert st["started_at"] and st["completed_at"]
        assert st["has_current_extraction"] is True  # Run 1 is still available
        assert st["current_extraction"]["run_number"] == 1

        # What the UI shows in the row: the evidence list/metadata.
        row = api.evidence_row(client, case_id, eid)
        assert row["processing_status"] == "failed"
        assert row["processing_error"] == MISSING_MESSAGE
        assert row["processing_error_code"] == "storage_missing"
        assert row["processing_attempts"] == 2

        # What the UI polls for the toolbar and badges: the case summary.
        assert api.summary(client, case_id)["counts"] == {
            "total": 1, "pending": 0, "processing": 0, "completed": 0, "failed": 1,
        }
        item = api.summary_item(client, case_id, eid)
        assert item["status"] == "failed" and item["error_code"] == "storage_missing"
        assert item["outcome"] == "ok" and item["run_number"] == 1  # still shows Run 1
        assert item["segment_count"] == 4 and item["attempts"] == 2

        # History: the failed run is recorded, never current, and has no segments.
        history = api.runs(client, case_id, eid)
        assert api.digest(history) == [(1, "completed", True), (2, "failed", False)]
        failed = history[0]
        assert failed["outcome"] is None
        assert failed["error_code"] == "storage_missing"
        assert failed["error_message"] == MISSING_MESSAGE
        assert failed["segment_count"] == 0
        assert api.segments(client, case_id, eid, failed["id"]) == []

        # Run 1 is untouched: identical ids and content, still the current run.
        assert api.segments(client, case_id, eid) == run1_segments
        assert current_flags(db_session, eid).count(True) == 1

    # The file is back. Retry creates a third attempt that succeeds.
    res = api.retry(client, case_id, eid)
    assert res.status_code == 202
    assert res.json() == {"queued": [eid], "skipped": []}

    st = api.status(client, case_id, eid)
    assert st["status"] == "completed"
    assert st["attempts"] == 3
    assert st["error"] is None and st["error_code"] is None
    row = api.evidence_row(client, case_id, eid)
    assert row["processing_status"] == "completed"
    assert row["processing_error"] is None and row["processing_error_code"] is None
    assert api.summary(client, case_id)["counts"]["completed"] == 1
    assert api.summary(client, case_id)["counts"]["failed"] == 0

    history = api.runs(client, case_id, eid)
    assert api.digest(history) == [
        (1, "completed", False),
        (2, "failed", False),
        (3, "completed", True),
    ]
    assert current_flags(db_session, eid).count(True) == 1
    run3 = history[0]
    assert run3["run_number"] == 3 and run3["segment_count"] == 4

    # Every run keeps its own data. Run 1 is byte-identical to before the failure.
    assert api.segments(client, case_id, eid, run1["id"]) == run1_segments
    run3_segments = api.segments(client, case_id, eid)
    assert {s["extraction_id"] for s in run3_segments} == {run3["id"]}
    assert {s["id"] for s in run3_segments}.isdisjoint({s["id"] for s in run1_segments})
    assert api.content_of(run3_segments) == api.content_of(run1_segments)
    assert api.segments(client, case_id, eid, history[1]["id"]) == []  # failed run

    # A completed item cannot be "retried".
    assert api.retry(client, case_id, eid).status_code == 409


# --- the very first attempt fails ------------------------------------------------------


def test_first_attempt_failure_then_retry_recovers(client, storage, db_session):
    case_id = api.make_case(client)
    ev = api.upload(client, case_id, api.unique_csv(2))
    eid, sha = ev["id"], ev["sha256"]
    base = f"/api/cases/{case_id}/evidence/{eid}"

    with hidden_blob(storage, sha):
        assert api.process(client, case_id, eid).status_code == 202

        st = api.status(client, case_id, eid)
        assert st["status"] == "failed"
        assert st["error_code"] == "storage_missing" and st["error"] == MISSING_MESSAGE
        assert st["attempts"] == 1
        assert st["has_current_extraction"] is False
        assert st["current_extraction"] is None

        item = api.summary_item(client, case_id, eid)
        assert item["status"] == "failed"
        assert item["outcome"] is None and item["run_number"] is None
        assert item["segment_count"] == 0

        # Nothing to show yet: no current extraction and no current segments.
        assert client.get(f"{base}/extraction").status_code == 404
        assert api.segments_response(client, case_id, eid).status_code == 404

        history = api.runs(client, case_id, eid)
        assert api.digest(history) == [(1, "failed", False)]
        assert history[0]["error_code"] == "storage_missing"
        assert current_flags(db_session, eid) == [False]

    assert api.retry(client, case_id, eid).status_code == 202

    st = api.status(client, case_id, eid)
    assert st["status"] == "completed" and st["attempts"] == 2
    assert st["error"] is None and st["has_current_extraction"] is True

    history = api.runs(client, case_id, eid)
    assert api.digest(history) == [(1, "failed", False), (2, "completed", True)]
    assert len(api.segments(client, case_id, eid)) == 3  # header + 2 rows
    assert api.segments(client, case_id, eid, history[1]["id"]) == []  # the failed run
    assert client.get(f"{base}/extraction").json()["run_number"] == 2


# --- retry while the problem persists --------------------------------------------------


def test_each_retry_while_the_problem_persists_is_a_new_failed_attempt(client, storage):
    case_id = api.make_case(client)
    ev = api.upload(client, case_id, api.unique_csv(2))
    eid, sha = ev["id"], ev["sha256"]

    with hidden_blob(storage, sha):
        api.process(client, case_id, eid)
        for expected_attempts in (2, 3):
            res = api.retry(client, case_id, eid)
            assert res.status_code == 202 and res.json()["queued"] == [eid]
            st = api.status(client, case_id, eid)
            assert st["status"] == "failed"
            assert st["attempts"] == expected_attempts
            assert st["error_code"] == "storage_missing"

        history = api.runs(client, case_id, eid)
        assert api.digest(history) == [
            (1, "failed", False),
            (2, "failed", False),
            (3, "failed", False),
        ]
        assert all(r["error_code"] == "storage_missing" for r in history)
        assert all(r["segment_count"] == 0 for r in history)
        assert api.status(client, case_id, eid)["has_current_extraction"] is False

    assert api.retry(client, case_id, eid).status_code == 202
    assert api.status(client, case_id, eid)["status"] == "completed"
    assert api.digest(api.runs(client, case_id, eid)) == [
        (1, "failed", False),
        (2, "failed", False),
        (3, "failed", False),
        (4, "completed", True),
    ]


# --- failure raised by the real CSV extractor -----------------------------------------


@pytest.mark.parametrize("variant", sorted(CORRUPT_UTF16))
def test_corrupt_csv_fails_in_the_real_extractor_and_retry_fails_again(
    client, variant, db_session
):
    case_id = api.make_case(client)
    ev = api.upload(client, case_id, CORRUPT_UTF16[variant], name="corrupt-utf16.csv")
    eid = ev["id"]
    assert ev["evidence_type"] == "tabular"  # it passed upload validation
    base = f"/api/cases/{case_id}/evidence/{eid}"

    assert api.process(client, case_id, eid).status_code == 202
    st = api.status(client, case_id, eid)
    assert st["status"] == "failed"
    assert st["error_code"] == "corrupt_file"
    assert st["error"] == CORRUPT_UTF16_MESSAGE
    assert st["attempts"] == 1
    assert api.evidence_row(client, case_id, eid)["processing_error_code"] == "corrupt_file"
    assert api.summary(client, case_id)["counts"]["failed"] == 1

    # A permanently bad file: retry runs again and fails again, as a new attempt.
    res = api.retry(client, case_id, eid)
    assert res.status_code == 202 and res.json()["queued"] == [eid]
    st = api.status(client, case_id, eid)
    assert st["status"] == "failed" and st["attempts"] == 2
    assert st["error_code"] == "corrupt_file" and st["error"] == CORRUPT_UTF16_MESSAGE

    history = api.runs(client, case_id, eid)
    assert api.digest(history) == [(1, "failed", False), (2, "failed", False)]
    assert all(r["error_code"] == "corrupt_file" for r in history)
    assert all(r["extractor"] == "csv" for r in history)
    assert current_flags(db_session, eid) == [False, False]
    assert client.get(f"{base}/extraction").status_code == 404
    assert api.segments_response(client, case_id, eid).status_code == 404

    # Retry stays available while the item is failed.
    assert api.retry(client, case_id, eid).status_code == 202
    assert api.status(client, case_id, eid)["attempts"] == 3


# --- other items are not affected ---------------------------------------------------------


def test_a_failure_leaves_other_items_and_other_cases_untouched(client, storage):
    case_a = api.make_case(client, "A")
    case_b = api.make_case(client, "B")
    a1 = api.upload(client, case_a, api.unique_csv(3), name="a1.csv")
    a2 = api.upload(client, case_a, api.unique_csv(3), name="a2.csv")
    b1 = api.upload(client, case_b, api.unique_csv(3), name="b1.csv")
    for case_id, ev in ((case_a, a1), (case_a, a2), (case_b, b1)):
        api.process(client, case_id, ev["id"])
    before = {
        ev["id"]: api.segments(client, case_id, ev["id"])
        for case_id, ev in ((case_a, a1), (case_a, a2), (case_b, b1))
    }

    with hidden_blob(storage, a1["sha256"]):
        for case_id, ev in ((case_a, a1), (case_a, a2), (case_b, b1)):
            assert api.process(client, case_id, ev["id"], force=True).status_code == 202

        # Only A1 failed. Its siblings ran their forced re-run normally.
        assert api.status(client, case_a, a1["id"])["status"] == "failed"
        assert api.status(client, case_a, a2["id"])["status"] == "completed"
        assert api.status(client, case_b, b1["id"])["status"] == "completed"
        assert api.digest(api.runs(client, case_a, a1["id"])) == [
            (1, "completed", True),
            (2, "failed", False),
        ]
        for case_id, ev in ((case_a, a2), (case_b, b1)):
            assert api.digest(api.runs(client, case_id, ev["id"])) == [
                (1, "completed", False),
                (2, "completed", True),
            ]

    # Every item's first run is still exactly what it was before anything failed.
    for case_id, ev in ((case_a, a1), (case_a, a2), (case_b, b1)):
        first_run = api.runs(client, case_id, ev["id"])[-1]
        assert api.segments(client, case_id, ev["id"], first_run["id"]) == before[ev["id"]]
    assert api.summary(client, case_b)["counts"]["failed"] == 0
