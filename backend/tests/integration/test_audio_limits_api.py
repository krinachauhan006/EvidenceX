"""Audio limits through the HTTP API: failures are recorded as failed runs, earlier
runs stay available and retry recovers. A fake model stands in for Whisper."""

from __future__ import annotations

from types import SimpleNamespace

from app.modules.processing.extractors import audio as audio_mod
from app.modules.processing.extractors.audio import AudioExtractor
from tests.fixtures.processing_samples import make_wav
from tests.unit.test_audio_decoding import RecordingModel, transcriber_with


def setup_case(client, registry, seconds=2.0, segments=None):
    registry.register("audio/wav", AudioExtractor(transcriber_with(RecordingModel(segments))))
    case_id = client.post("/api/cases", json={"title": "Audio limits"}).json()["id"]
    ev = client.post(
        f"/api/cases/{case_id}/evidence",
        files={"file": ("call.wav", make_wav(seconds), "application/octet-stream")},
    ).json()
    return case_id, ev["id"], f"/api/cases/{case_id}/evidence/{ev['id']}"


def test_over_limit_audio_fails_as_limit_exceeded_and_keeps_the_earlier_run(
    client, registry, settings
):
    case_id, evidence_id, base = setup_case(client, registry, seconds=2.0)
    client.post(f"{base}/process")
    run1 = client.get(f"{base}/extraction").json()
    first_segments = client.get(f"{base}/segments").json()["items"]

    settings.max_audio_seconds = 1  # now the 2 s file is over the limit
    client.post(f"{base}/process", json={"force": True})
    status = client.get(f"{base}/processing").json()
    assert status["status"] == "failed"
    assert status["error_code"] == "limit_exceeded"
    assert "MAX_AUDIO_SECONDS" in status["error"]
    assert status["current_extraction"]["id"] == run1["id"]  # earlier run still current
    runs = client.get(f"{base}/extractions").json()["items"]
    failed = next(r for r in runs if r["run_number"] == 2)
    assert failed["run_status"] == "failed" and failed["segment_count"] == 0
    assert client.get(f"{base}/segments").json()["items"] == first_segments  # unchanged

    settings.max_audio_seconds = 1200
    assert client.post(f"{base}/retry").status_code == 202
    assert client.get(f"{base}/processing").json()["status"] == "completed"


def test_timeout_fails_the_run_and_retry_recovers(client, registry, settings, monkeypatch):
    segments = [
        SimpleNamespace(
            start=0.0,
            end=1.0,
            text=" Words.",
            avg_logprob=-0.2,
            no_speech_prob=0.0,
            compression_ratio=1.0,
            words=None,
        )
    ]
    case_id, evidence_id, base = setup_case(client, registry, segments=segments)

    ticks = iter([0.0, 1.0, 999.0])
    monkeypatch.setattr(audio_mod, "_now", lambda: next(ticks, 999.0))
    settings.audio_timeout_seconds = 10
    client.post(f"{base}/process")
    status = client.get(f"{base}/processing").json()
    assert status["status"] == "failed" and status["error_code"] == "timeout"
    assert status["has_current_extraction"] is False  # no empty "success" was recorded
    [failed] = client.get(f"{base}/extractions").json()["items"]
    assert failed["run_status"] == "failed" and failed["outcome"] is None

    monkeypatch.setattr(audio_mod, "_now", lambda: 0.0)  # normal speed again
    client.post(f"{base}/retry")
    status = client.get(f"{base}/processing").json()
    assert status["status"] == "completed"
    assert [s["text"] for s in client.get(f"{base}/segments").json()["items"]] == ["Words."]


def test_segments_are_reported_as_unreviewed_original_text(client, registry):
    case_id, evidence_id, base = setup_case(client, registry)
    client.post(f"{base}/process")
    [segment] = client.get(f"{base}/segments").json()["items"]
    assert segment["review_status"] == "unreviewed"
    assert segment["text"] == "Synthetic words."
    assert segment["data"]["source"] == "machine_transcription"


def test_original_transcript_is_immutable_across_reprocessing(client, registry):
    case_id, evidence_id, base = setup_case(client, registry)
    client.post(f"{base}/process")
    run1 = client.get(f"{base}/extraction").json()
    before = client.get(f"{base}/segments").json()["items"]

    # The engine now "hears" something different; the first run must not change.
    other = [
        SimpleNamespace(
            start=0.0,
            end=1.0,
            text=" Different words.",
            avg_logprob=-0.1,
            no_speech_prob=0.0,
            compression_ratio=1.0,
            words=None,
        )
    ]
    registry.register("audio/wav", AudioExtractor(transcriber_with(RecordingModel(other))))
    client.post(f"{base}/process", json={"force": True})

    after_run1 = client.get(f"{base}/segments?extraction_id={run1['id']}").json()["items"]
    assert after_run1 == before
    current = client.get(f"{base}/segments").json()["items"]
    assert [s["text"] for s in current] == ["Different words."]
    assert {s["id"] for s in current}.isdisjoint({s["id"] for s in before})
    # There is no API to edit a segment's text.
    seg_id = before[0]["id"]
    for method in ("put", "patch"):
        res = getattr(client, method)(f"{base}/segments/{seg_id}", json={"text": "edited"})
        assert res.status_code in (404, 405)
