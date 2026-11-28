"""EXTERNAL_WORKER_MIMES: the API server never claims file types left to the worker.

On the Vercel deployment OCR, speech and video engines are missing. With the setting,
those items stay "pending" (skip reason ``external_worker``) instead of being claimed
and marked failed, and every other file type is processed exactly as before.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core import config as config_module
from app.core.config import Settings
from app.modules.evidence.models import Evidence
from app.modules.processing.models import Extraction
from tests.fixtures.fake_extractors import FakeOcrExtractor
from tests.fixtures.sample_files import CSV_BYTES, PNG_BYTES, WAV_BYTES

WORKER_MIMES = "image/png,image/jpeg,image/webp,audio/wav,audio/mpeg,audio/mp4,video/mp4"


# --- configuration --------------------------------------------------------------


def test_setting_is_parsed_normalised_and_deduplicated():
    s = Settings(EXTERNAL_WORKER_MIMES=" Image/PNG, audio/wav ,image/png,, ; video/mp4 ")
    assert s.external_worker_mimes == frozenset({"image/png", "audio/wav", "video/mp4"})
    assert s.external_worker_mimes_raw == "image/png,audio/wav,video/mp4"


def test_setting_defaults_to_none():
    assert Settings().external_worker_mimes == frozenset()
    assert Settings(EXTERNAL_WORKER_MIMES="").external_worker_mimes == frozenset()


@pytest.mark.parametrize("bad", ["png", "image/", "/png", "image/png/x", "image png", "imäge/png"])
def test_malformed_entries_are_refused(bad):
    with pytest.raises(ValidationError, match="EXTERNAL_WORKER_MIMES"):
        Settings(EXTERNAL_WORKER_MIMES=f"audio/wav,{bad}")


def test_setting_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("EXTERNAL_WORKER_MIMES", "image/png,audio/wav")
    assert Settings().external_worker_mimes == frozenset({"image/png", "audio/wav"})


# --- the gate on the API ----------------------------------------------------------


@pytest.fixture
def gated(client, settings, registry, monkeypatch):
    """The API with the gate on, a fake OCR engine for PNG, and the same settings
    visible to response schemas (which read the global settings)."""
    settings.external_worker_mimes_raw = WORKER_MIMES
    monkeypatch.setattr(config_module, "get_settings", lambda: settings)
    registry.register("image/png", FakeOcrExtractor())
    return client


def _case(client) -> str:
    return client.post("/api/cases", json={"title": "Gate", "description": None}).json()["id"]


def _upload(client, case_id, name, data):
    res = client.post(
        f"/api/cases/{case_id}/evidence", files={"file": (name, data, "application/octet-stream")}
    )
    assert res.status_code == 201, res.text
    return res.json()


def _extractions(db, evidence_id) -> int:
    return db.scalar(
        select(func.count()).select_from(Extraction).where(Extraction.evidence_id == evidence_id)
    )


def test_process_pending_skips_worker_types_and_processes_the_rest(gated, db_session):
    case_id = _case(gated)
    png = _upload(gated, case_id, "gate.png", PNG_BYTES)
    csv = _upload(gated, case_id, "ledger.csv", CSV_BYTES)

    res = gated.post(f"/api/cases/{case_id}/evidence/process-pending")
    assert res.status_code == 202
    body = res.json()
    assert body["queued"] == [csv["id"]]
    assert body["skipped"] == [{"evidence_id": png["id"], "reason": "external_worker"}]

    db_session.expire_all()
    img = db_session.scalar(select(Evidence).where(Evidence.id == uuid.UUID(png["id"])))
    # Not claimed, not failed, nothing recorded: it waits for the worker.
    assert img.processing_status == "pending"
    assert img.processing_attempts == 0
    assert img.processing_error_code is None
    assert _extractions(db_session, img.id) == 0
    tab = db_session.scalar(select(Evidence).where(Evidence.original_filename == "ledger.csv"))
    assert tab.processing_status == "completed"


def test_single_process_force_and_retry_are_skipped_for_worker_types(gated, db_session):
    case_id = _case(gated)
    png = _upload(gated, case_id, "gate.png", PNG_BYTES)
    base = f"/api/cases/{case_id}/evidence/{png['id']}"

    for body in (None, {"force": True}):
        res = gated.post(f"{base}/process", json=body)
        assert res.status_code == 202
        assert res.json() == {
            "queued": [],
            "skipped": [{"evidence_id": png["id"], "reason": "external_worker"}],
        }

    # An item this server failed earlier (before the setting) is left for the worker.
    ev = db_session.scalar(select(Evidence).where(Evidence.original_filename == "gate.png"))
    ev.processing_status = "failed"
    ev.processing_error_code = "dependency_missing"
    ev.processing_attempts = 1
    db_session.flush()
    res = gated.post(f"{base}/retry")
    assert res.status_code == 202
    assert res.json()["skipped"][0]["reason"] == "external_worker"
    db_session.expire_all()
    ev = db_session.get(Evidence, ev.id)
    assert (ev.processing_status, ev.processing_attempts) == ("failed", 1)
    assert _extractions(db_session, ev.id) == 0


def test_summary_and_evidence_responses_flag_worker_types(gated):
    case_id = _case(gated)
    png = _upload(gated, case_id, "gate.png", PNG_BYTES)
    wav = _upload(gated, case_id, "call.wav", WAV_BYTES)
    csv = _upload(gated, case_id, "ledger.csv", CSV_BYTES)
    assert png["external_worker"] is True and wav["external_worker"] is True
    assert csv["external_worker"] is False

    summary = gated.get(f"/api/cases/{case_id}/processing").json()
    flags = {i["original_filename"]: i["external_worker"] for i in summary["items"]}
    assert flags == {"gate.png": True, "call.wav": True, "ledger.csv": False}
    # Waiting items are counted as pending, never as failed.
    assert summary["counts"]["pending"] == 3 and summary["counts"]["failed"] == 0

    listed = gated.get(f"/api/cases/{case_id}/evidence").json()["items"]
    assert {e["original_filename"]: e["external_worker"] for e in listed}["gate.png"] is True


def test_without_the_setting_processing_is_unchanged(client, registry, db_session):
    fake = FakeOcrExtractor()
    registry.register("image/png", fake)
    case_id = _case(client)
    png = _upload(client, case_id, "gate.png", PNG_BYTES)
    assert png["external_worker"] is False

    res = client.post(f"/api/cases/{case_id}/evidence/process-pending")
    assert res.json()["queued"] == [png["id"]]
    assert fake.calls == 1
    ev = db_session.scalar(select(Evidence).where(Evidence.original_filename == "gate.png"))
    db_session.refresh(ev)
    assert ev.processing_status == "completed"
