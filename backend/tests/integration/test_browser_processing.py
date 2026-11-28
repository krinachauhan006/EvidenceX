"""In-browser processing through the API (browser_service.py).

The browser's engine output is simulated with fixed payloads (no OCR or speech engine
runs here). What is tested is the server side: the claim, validation against the
stored file, persistence through the shared repository, duplicate and stale-attempt
refusal, failure recording, authorization, the worker's view of browser failures, and
that saved segments feed search and analysis like any other run. All data is synthetic.
"""

from __future__ import annotations

import io
import json
import uuid
import wave
from contextlib import contextmanager
from datetime import timedelta

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.core import config as config_module
from app.core.db_types import as_utc, utcnow
from app.modules.analysis.models import Claim
from app.modules.evidence.models import Evidence
from app.modules.processing.browser_service import FAILURE_MESSAGES, BrowserProcessingService
from app.modules.processing.models import Extraction, ExtractionSegment
from app.modules.processing.router import get_browser_service
from app.worker import find_candidates
from tests.fixtures.fake_extractors import FakeOcrExtractor
from tests.fixtures.sample_files import CSV_BYTES, MP4_BYTES

WORKER_MIMES = "image/png,image/jpeg,image/webp,audio/wav,audio/mpeg,audio/mp4,video/mp4"
RECEIPT = "Delivery receipt: Truck arrived 10:30 on 12 October 2026."


def png(width: int = 200, height: int = 100) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="PNG")
    return buf.getvalue()


def wav(seconds: float = 2.0, rate: int = 16_000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


@pytest.fixture
def gated(client, settings, registry, storage, db_session, monkeypatch):
    """The deployment configuration: images/audio/video left to a worker, so browsers
    may process them. The browser service uses the test session, settings and storage."""
    settings.external_worker_mimes_raw = WORKER_MIMES
    monkeypatch.setattr(config_module, "get_settings", lambda: settings)
    client.app.dependency_overrides[get_browser_service] = lambda: BrowserProcessingService(
        db_session, settings, storage
    )
    return client


def new_case(c) -> str:
    return c.post("/api/cases", json={"title": "Browser", "description": None}).json()["id"]


def upload(c, case_id: str, name: str, data: bytes) -> dict:
    r = c.post(
        f"/api/cases/{case_id}/evidence", files={"file": (name, data, "application/octet-stream")}
    )
    assert r.status_code == 201, r.text
    return r.json()


def base(case_id: str, evidence_id: str) -> str:
    return f"/api/cases/{case_id}/evidence/{evidence_id}/browser-processing"


def claim(c, case_id, ev, **body):
    return c.post(f"{base(case_id, ev['id'])}/claim", json=body or None)


def line(text: str, bbox, words=None, confidence=None) -> dict:
    out = {"text": text, "bbox": list(bbox), "words": words or []}
    if confidence is not None:
        out["confidence"] = confidence
    return out


def image_payload(ev: dict, run: int, *, width=200, height=100, lines=None, sha=None) -> dict:
    if lines is None:
        lines = [
            line(
                RECEIPT,
                (10, 10, 190, 30),
                words=[
                    {"text": "Delivery", "bbox": [10, 10, 60, 30], "confidence": 0.9},
                    {"text": "receipt:", "bbox": [62, 10, 110, 30], "confidence": 0.7},
                ],
            )
        ]
    return {
        "run_number": run,
        "source_sha256": sha or ev["sha256"],
        "duration_ms": 1234,
        "engine": {"ocr_engine_version": "7.0.0", "device": "wasm"},
        "result": {
            "kind": "image",
            "width": width,
            "height": height,
            "language": "eng",
            "lines": lines,
        },
    }


def submit(c, case_id, ev, payload):
    return c.post(f"{base(case_id, ev['id'])}/result", json=payload)


def evidence_row(db, evidence_id) -> Evidence:
    db.expire_all()
    return db.get(Evidence, uuid.UUID(evidence_id))


def runs(db, evidence_id) -> list[Extraction]:
    return list(
        db.scalars(
            select(Extraction)
            .where(Extraction.evidence_id == uuid.UUID(evidence_id))
            .order_by(Extraction.run_number)
        )
    )


def segment_count(db, evidence_id) -> int:
    return db.scalar(
        select(func.count())
        .select_from(ExtractionSegment)
        .where(ExtractionSegment.evidence_id == uuid.UUID(evidence_id))
    )


# --- image ---------------------------------------------------------------------------


def test_image_claim_submit_persists_segments_and_completes(gated, db_session):
    case_id = new_case(gated)
    ev = upload(gated, case_id, "receipt.png", png())
    assert ev["browser_processing"] is True and ev["external_worker"] is True

    r = claim(gated, case_id, ev)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_number"] == 1 and body["kind"] == "image" and body["sha256"] == ev["sha256"]
    assert body["heartbeat_seconds"] < body["stale_seconds"]
    # Claimed, not completed: nothing is saved until the result is accepted.
    assert evidence_row(db_session, ev["id"]).processing_status == "processing"
    assert runs(db_session, ev["id"]) == []

    r = submit(gated, case_id, ev, image_payload(ev, 1))
    assert r.status_code == 200, r.text
    status = r.json()
    assert status["status"] == "completed" and status["has_current_extraction"] is True
    run = status["current_extraction"]
    assert run["extractor"] == "browser-tesseract.js" and run["extractor_version"] == "7.0.0"
    assert run["outcome"] == "ok" and run["segment_count"] == 1
    assert run["doc_metadata"]["processed_in"] == "browser"
    assert run["doc_metadata"]["size_verified_by_server"] is True
    assert "processed_in_browser" in [w["code"] for w in run["warnings"]]

    seg = gated.get(f"/api/cases/{case_id}/evidence/{ev['id']}/segments").json()["items"][0]
    assert seg["segment_type"] == "ocr_line" and seg["text"] == RECEIPT
    assert seg["locator"] == {
        "kind": "image",
        "bbox": [10.0, 10.0, 190.0, 30.0],
        "width": 200,
        "height": 100,
        "unit": "px",
    }
    # Engine confidence is recomputed on the server as the mean word confidence.
    assert seg["engine_confidence"] == pytest.approx(0.8)
    assert seg["language"] == "eng"
    item = gated.get(f"/api/cases/{case_id}/processing").json()["items"][0]
    assert item["status"] == "completed" and item["browser_processing"] is True


def test_duplicate_and_late_submissions_are_refused_and_save_nothing(gated, db_session):
    case_id = new_case(gated)
    ev = upload(gated, case_id, "receipt.png", png())
    claim(gated, case_id, ev)
    assert submit(gated, case_id, ev, image_payload(ev, 1)).status_code == 200

    again = submit(gated, case_id, ev, image_payload(ev, 1))
    assert again.status_code == 409
    assert len(runs(db_session, ev["id"])) == 1 and segment_count(db_session, ev["id"]) == 1

    # Already completed: a plain claim is refused; force adds run 2.
    assert claim(gated, case_id, ev).status_code == 409
    second = claim(gated, case_id, ev, force=True)
    assert second.status_code == 200 and second.json()["run_number"] == 2
    # A result for the old run 1 cannot overwrite the new attempt.
    assert submit(gated, case_id, ev, image_payload(ev, 1)).status_code == 409
    assert submit(gated, case_id, ev, image_payload(ev, 2)).status_code == 200
    history = runs(db_session, ev["id"])
    assert [(r.run_number, r.is_current) for r in history] == [(1, False), (2, True)]


def test_a_second_tab_cannot_claim_an_item_being_processed(gated):
    case_id = new_case(gated)
    ev = upload(gated, case_id, "receipt.png", png())
    assert claim(gated, case_id, ev).status_code == 200
    r = claim(gated, case_id, ev)
    assert r.status_code == 409 and "already being processed" in r.json()["detail"]


def test_an_abandoned_claim_can_be_taken_over_after_the_browser_stale_time(gated, db_session):
    case_id = new_case(gated)
    ev = upload(gated, case_id, "receipt.png", png())
    claim(gated, case_id, ev)
    row = evidence_row(db_session, ev["id"])
    row.processing_started_at = utcnow() - timedelta(seconds=301)
    db_session.flush()
    item = gated.get(f"/api/cases/{case_id}/processing").json()["items"][0]
    assert item["status"] == "processing" and item["browser_reclaimable"] is True

    r = claim(gated, case_id, ev)
    assert r.status_code == 200 and r.json()["run_number"] == 2
    assert submit(gated, case_id, ev, image_payload(ev, 1)).status_code == 409
    assert submit(gated, case_id, ev, image_payload(ev, 2)).status_code == 200


def test_heartbeat_keeps_only_the_current_claim_alive(gated, db_session):
    case_id = new_case(gated)
    ev = upload(gated, case_id, "receipt.png", png())
    claim(gated, case_id, ev)
    row = evidence_row(db_session, ev["id"])
    row.processing_started_at = utcnow() - timedelta(seconds=200)
    db_session.flush()
    r = gated.post(f"{base(case_id, ev['id'])}/heartbeat", json={"run_number": 1})
    assert r.status_code == 204
    started = evidence_row(db_session, ev["id"]).processing_started_at
    assert utcnow() - as_utc(started) < timedelta(seconds=30)
    assert (
        gated.post(f"{base(case_id, ev['id'])}/heartbeat", json={"run_number": 7}).status_code
        == 409
    )


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"sha": "0" * 64}, "not the stored file"),
        ({"width": 201}, "size does not match"),
        ({"lines": [line("Outside", (10, 10, 260, 30))]}, "outside the image"),
        ({"lines": [line("Backwards", (50, 10, 20, 30))]}, "wrong order"),
    ],
)
def test_results_that_do_not_fit_the_stored_file_are_refused_and_recorded(
    gated, db_session, change, reason
):
    case_id = new_case(gated)
    ev = upload(gated, case_id, "receipt.png", png())
    claim(gated, case_id, ev)
    r = submit(gated, case_id, ev, image_payload(ev, 1, **change))
    assert r.status_code == 400 and reason in r.json()["detail"]
    row = evidence_row(db_session, ev["id"])
    assert row.processing_status == "failed"
    assert row.processing_error_code == "browser_result_rejected"
    assert segment_count(db_session, ev["id"]) == 0
    (failed,) = runs(db_session, ev["id"])
    assert failed.run_status == "failed" and failed.is_current is False
    # The failure is recoverable: the item can be claimed and processed again.
    assert claim(gated, case_id, ev).json()["run_number"] == 2
    assert submit(gated, case_id, ev, image_payload(ev, 2)).status_code == 200


def test_non_finite_numbers_and_unknown_fields_are_refused(gated):
    case_id = new_case(gated)
    ev = upload(gated, case_id, "receipt.png", png())
    claim(gated, case_id, ev)
    payload = image_payload(ev, 1)
    payload["result"]["lines"][0]["bbox"][0] = float("nan")
    # Python's JSON parser accepts the NaN literal, so the server must check it itself.
    r = gated.post(
        f"{base(case_id, ev['id'])}/result",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400 and "finite" in r.json()["detail"]
    claim(gated, case_id, ev)  # the refusal failed run 1; claim run 2
    extra = image_payload(ev, 2)
    extra["status"] = "completed"  # a client cannot set the status
    assert submit(gated, case_id, ev, extra).status_code == 422


def test_a_result_of_the_wrong_kind_is_refused(gated):
    case_id = new_case(gated)
    ev = upload(gated, case_id, "receipt.png", png())
    claim(gated, case_id, ev)
    payload = image_payload(ev, 1)
    payload["result"] = {"kind": "audio", "duration_seconds": 2.0, "segments": []}
    r = submit(gated, case_id, ev, payload)
    assert r.status_code == 400 and "audio result was sent for image" in r.json()["detail"]


def test_an_image_with_no_text_is_completed_as_empty_not_ok(gated):
    case_id = new_case(gated)
    ev = upload(gated, case_id, "blank.png", png())
    claim(gated, case_id, ev)
    status = submit(gated, case_id, ev, image_payload(ev, 1, lines=[])).json()
    assert status["status"] == "completed"
    assert status["current_extraction"]["outcome"] == "empty"
    assert "no_text_detected" in [w["code"] for w in status["current_extraction"]["warnings"]]


# --- audio and video --------------------------------------------------------------------


def audio_payload(ev, run, *, duration=2.0, segments=None) -> dict:
    return {
        "run_number": run,
        "source_sha256": ev["sha256"],
        "duration_ms": 5000,
        "engine": {
            "speech_engine_version": "4.3.2",
            "speech_model": "onnx-community/whisper-tiny",
            "device": "wasm",
        },
        "result": {
            "kind": "audio",
            "duration_seconds": duration,
            "language": "english",
            "segments": segments
            if segments is not None
            else [
                {"start": 0.0, "end": 1.2, "text": " The truck arrived at half past ten. "},
                {"start": 1.2, "end": 2.4, "text": "It was raining."},
            ],
        },
    }


def test_audio_transcript_is_saved_with_times_and_no_invented_confidence(gated, db_session):
    case_id = new_case(gated)
    ev = upload(gated, case_id, "call.wav", wav(2.0))
    assert claim(gated, case_id, ev).json()["kind"] == "audio"
    status = submit(gated, case_id, ev, audio_payload(ev, 1)).json()
    run = status["current_extraction"]
    assert status["status"] == "completed" and run["extractor"] == "browser-whisper"
    assert run["doc_metadata"]["duration_verified_by_server"] is True
    # 2.4 s ends past the 2.0 s recording: clamped (within tolerance) and reported.
    assert "timestamps_clamped" in [w["code"] for w in run["warnings"]]
    segs = gated.get(f"/api/cases/{case_id}/evidence/{ev['id']}/segments").json()["items"]
    assert [s["text"] for s in segs] == ["The truck arrived at half past ten.", "It was raining."]
    assert segs[0]["locator"] == {"kind": "audio", "start": 0.0, "end": 1.2}
    assert (segs[0]["t_start"], segs[0]["t_end"]) == (0.0, 1.2)
    assert segs[1]["locator"]["end"] == 2.0
    assert all(s["engine_confidence"] is None for s in segs)


def test_audio_whose_duration_does_not_match_the_stored_wav_is_refused(gated):
    case_id = new_case(gated)
    ev = upload(gated, case_id, "call.wav", wav(2.0))
    claim(gated, case_id, ev)
    r = submit(gated, case_id, ev, audio_payload(ev, 1, duration=9.0, segments=[]))
    assert r.status_code == 400 and "duration does not match" in r.json()["detail"]


def test_audio_segment_far_past_the_end_is_refused(gated):
    case_id = new_case(gated)
    ev = upload(gated, case_id, "call.wav", wav(2.0))
    claim(gated, case_id, ev)
    bad = [{"start": 0.0, "end": 5.0, "text": "Too long."}]
    r = submit(gated, case_id, ev, audio_payload(ev, 1, segments=bad))
    assert r.status_code == 400 and "beyond the end" in r.json()["detail"]


def video_payload(ev, run, frames=None, soundtrack="transcribed") -> dict:
    return {
        "run_number": run,
        "source_sha256": ev["sha256"],
        "duration_ms": 9000,
        "engine": {"ocr_engine_version": "7.0.0", "speech_engine_version": "4.3.2"},
        "result": {
            "kind": "video",
            "duration_seconds": 25.0,
            "frame_width": 640,
            "frame_height": 360,
            "interval_seconds": 10.0,
            "ocr_language": "eng",
            "frames": frames
            if frames is not None
            else [
                {"t": 0.0, "sampling": "first_frame", "lines": [line("DOCK 4", (20, 20, 120, 50))]},
                {"t": 10.0, "sampling": "interval", "lines": [line("x", (1, 1, 5, 5))]},
                {"t": 20.0, "sampling": "interval", "lines": []},
            ],
            "soundtrack": soundtrack,
            "transcript_language": "english",
            "transcript": [{"start": 3.0, "end": 6.5, "text": "Pallets unloaded."}],
        },
    }


def test_video_frames_ocr_lines_and_soundtrack_are_saved_on_one_timeline(gated, db_session):
    case_id = new_case(gated)
    ev = upload(gated, case_id, "dock.mp4", MP4_BYTES)
    assert claim(gated, case_id, ev).json()["kind"] == "video"
    status = submit(gated, case_id, ev, video_payload(ev, 1)).json()
    run = status["current_extraction"]
    assert run["extractor"] == "browser-video" and run["outcome"] == "ok"
    assert run["doc_metadata"]["frame_times"] == [0.0, 10.0, 20.0]
    assert "sampled_frames_only" in [w["code"] for w in run["warnings"]]
    segs = gated.get(f"/api/cases/{case_id}/evidence/{ev['id']}/segments").json()["items"]
    kinds = [(s["segment_type"], s["text"]) for s in segs]
    assert kinds == [
        ("video_frame", "DOCK 4"),
        ("video_ocr_line", "DOCK 4"),
        ("video_frame", None),  # the one-character line is dropped, as on the server
        ("video_frame", None),
        ("transcript_segment", "Pallets unloaded."),
    ]
    assert segs[1]["locator"]["bbox"] == [20.0, 20.0, 120.0, 50.0]
    assert (segs[1]["t_start"], segs[1]["t_end"]) == (0.0, 0.0)
    assert segs[4]["locator"] == {"kind": "audio", "start": 3.0, "end": 6.5}


def test_video_without_a_transcribed_soundtrack_is_partial_and_says_so(gated):
    case_id = new_case(gated)
    ev = upload(gated, case_id, "dock.mp4", MP4_BYTES)
    claim(gated, case_id, ev)
    run = submit(gated, case_id, ev, video_payload(ev, 1, soundtrack="not_transcribed")).json()[
        "current_extraction"
    ]
    assert run["outcome"] == "partial"
    assert "soundtrack_not_transcribed" in [w["code"] for w in run["warnings"]]
    assert run["doc_metadata"]["transcript_segments"] == 0


def test_video_frames_out_of_order_or_too_many_are_refused(gated, settings):
    case_id = new_case(gated)
    ev = upload(gated, case_id, "dock.mp4", MP4_BYTES)
    claim(gated, case_id, ev)
    frames = [{"t": 10.0, "sampling": "interval"}, {"t": 5.0, "sampling": "interval"}]
    r = submit(gated, case_id, ev, video_payload(ev, 1, frames=frames))
    assert r.status_code == 400 and "time order" in r.json()["detail"]

    settings.video_max_frames = 2
    claim(gated, case_id, ev)
    many = [{"t": float(i), "sampling": "interval"} for i in range(4)]
    r = submit(gated, case_id, ev, video_payload(ev, 2, frames=many))
    assert r.status_code == 400 and "more video frames" in r.json()["detail"]


# --- failures ------------------------------------------------------------------------------


@pytest.mark.parametrize("code", sorted(FAILURE_MESSAGES))
def test_reported_failures_store_the_server_message_and_stay_retryable(gated, db_session, code):
    case_id = new_case(gated)
    ev = upload(gated, case_id, "receipt.png", png())
    claim(gated, case_id, ev)
    r = gated.post(f"{base(case_id, ev['id'])}/failure", json={"run_number": 1, "code": code})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed" and body["error_code"] == code
    assert body["error"] == FAILURE_MESSAGES[code]
    assert segment_count(db_session, ev["id"]) == 0
    assert claim(gated, case_id, ev).status_code == 200  # retry


def test_failure_reports_accept_only_known_codes_and_the_current_run(gated):
    case_id = new_case(gated)
    ev = upload(gated, case_id, "receipt.png", png())
    claim(gated, case_id, ev)
    url = f"{base(case_id, ev['id'])}/failure"
    assert gated.post(url, json={"run_number": 1, "code": "corrupt_file"}).status_code == 422
    assert (
        gated.post(url, json={"run_number": 1, "code": "interrupted", "message": "x"}).status_code
        == 422
    )
    assert gated.post(url, json={"run_number": 3, "code": "interrupted"}).status_code == 409


def test_a_failed_forced_rerun_keeps_the_earlier_completed_run(gated, db_session):
    case_id = new_case(gated)
    ev = upload(gated, case_id, "receipt.png", png())
    claim(gated, case_id, ev)
    submit(gated, case_id, ev, image_payload(ev, 1))
    claim(gated, case_id, ev, force=True)
    r = gated.post(
        f"{base(case_id, ev['id'])}/failure", json={"run_number": 2, "code": "interrupted"}
    )
    assert r.json()["status"] == "completed" and r.json()["current_extraction"]["run_number"] == 1


# --- which items, and who --------------------------------------------------------------------


def test_types_the_server_processes_itself_are_not_offered_to_the_browser(gated, client):
    case_id = new_case(gated)
    csv = upload(gated, case_id, "ledger.csv", CSV_BYTES)
    assert csv["browser_processing"] is False
    assert claim(gated, case_id, csv).status_code == 409


def test_without_external_worker_types_the_server_keeps_processing_images(
    client, storage, db_session, settings
):
    client.app.dependency_overrides[get_browser_service] = lambda: BrowserProcessingService(
        db_session, settings, storage
    )
    case_id = new_case(client)
    ev = upload(client, case_id, "receipt.png", png())
    assert ev["browser_processing"] is False
    assert claim(client, case_id, ev).status_code == 409


def test_the_setting_turns_browser_processing_off(gated, settings):
    settings.browser_processing_enabled = False
    case_id = new_case(gated)
    ev = upload(gated, case_id, "receipt.png", png())
    assert ev["browser_processing"] is False and ev["external_worker"] is True
    assert claim(gated, case_id, ev).status_code == 409


def test_only_editors_of_the_case_can_process(gated, make_user, anon):
    case_id = new_case(gated)
    ev = upload(gated, case_id, "receipt.png", png())
    viewer = make_user("viewer@example.org", "Viewer")
    stranger = make_user("stranger@example.org", "Stranger")
    r = gated.post(
        f"/api/cases/{case_id}/members", json={"email": "viewer@example.org", "role": "viewer"}
    )
    assert r.status_code in (200, 201), r.text

    assert claim(viewer, case_id, ev).status_code == 403
    assert claim(stranger, case_id, ev).status_code == 404
    assert claim(anon, case_id, ev).status_code == 401
    # Another case's id cannot reach this evidence.
    other = new_case(gated)
    assert gated.post(f"{base(other, ev['id'])}/claim").status_code == 404

    assert claim(gated, case_id, ev).status_code == 200
    for c, expected in ((viewer, 403), (stranger, 404)):
        assert submit(c, case_id, ev, image_payload(ev, 1)).status_code == expected
        url = f"{base(case_id, ev['id'])}/failure"
        assert c.post(url, json={"run_number": 1, "code": "interrupted"}).status_code == expected


# --- worker and API runner regression ------------------------------------------------------


class _KeepTestData:
    """The test session, minus rollback (the worker's read-only query rolls back, which
    would discard this test's uncommitted data)."""

    def __init__(self, db) -> None:
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def rollback(self) -> None:
        pass


@contextmanager
def _shared(db):
    yield _KeepTestData(db)


def test_worker_still_sees_pending_items_and_retries_browser_failures(gated, db_session, settings):
    case_id = new_case(gated)
    pending = upload(gated, case_id, "pending.png", png())
    failed = upload(gated, case_id, "failed.png", png(120, 80))
    claim(gated, case_id, failed)
    gated.post(
        f"{base(case_id, failed['id'])}/failure",
        json={"run_number": 1, "code": "browser_decode_failed"},
    )
    found = {
        str(c.evidence_id): c.reason
        for c in find_candidates(lambda: _shared(db_session), settings, include_scanned_pdfs=False)
    }
    assert found[pending["id"]] == "pending"
    assert found[failed["id"]] == "browser_failed"


def test_worker_and_browser_never_hold_the_same_item(gated, db_session, runner, registry):
    registry.register("image/png", FakeOcrExtractor())
    case_id = new_case(gated)
    ev = upload(gated, case_id, "receipt.png", png())
    claim(gated, case_id, ev)
    # The worker's runner cannot claim an item a live browser holds.
    assert runner.run_one(uuid.UUID(case_id), uuid.UUID(ev["id"])) == "skipped"
    assert submit(gated, case_id, ev, image_payload(ev, 1)).status_code == 200

    ev2 = upload(gated, case_id, "second.png", png(120, 80))
    assert runner.run_one(uuid.UUID(case_id), uuid.UUID(ev2["id"])) == "completed"
    assert claim(gated, case_id, ev2).status_code == 409  # already completed by the worker


# --- downstream: same pipeline as worker results --------------------------------------------


def test_browser_segments_feed_search_and_analysis(gated, db_session):
    case_id = new_case(gated)
    ev = upload(gated, case_id, "receipt.png", png())
    claim(gated, case_id, ev)
    submit(gated, case_id, ev, image_payload(ev, 1))

    assert gated.post(f"/api/cases/{case_id}/analysis").status_code == 202
    run = gated.get(f"/api/cases/{case_id}/analysis/latest").json()["run"]
    assert run["status"] == "completed", run
    seg_ids = set(
        db_session.scalars(
            select(ExtractionSegment.id).where(ExtractionSegment.evidence_id == uuid.UUID(ev["id"]))
        )
    )
    claims = list(db_session.scalars(select(Claim).where(Claim.case_id == uuid.UUID(case_id))))
    assert claims, "the rule-based extractor finds the time statement"
    assert all(c.segment_id in seg_ids for c in claims)

    hits = gated.get(f"/api/cases/{case_id}/search", params={"q": "truck arrived"}).json()
    segment_hits = [h for h in hits["items"] if h["kind"] == "segment"]
    assert segment_hits and segment_hits[0]["evidence_name"] == "receipt.png"
    assert segment_hits[0]["locator"]["kind"] == "image"
