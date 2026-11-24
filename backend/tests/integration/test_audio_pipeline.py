"""Audio through the HTTP API with the real PyAV decoder and a stand-in model.

Uses the isolated test database and temporary blob store from conftest. The model is
replaced by a small fake, so no model is loaded or downloaded.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from app.modules.processing.extractors.audio import AudioExtractor, FasterWhisperTranscriber
from tests.fixtures.processing_samples import make_wav
from tests.fixtures.sample_files import WAV_BYTES


class FakeModel:
    def __init__(self, error: Exception | None = None) -> None:
        self.received: list[object] = []
        self.error = error

    def transcribe(self, audio, **kwargs):
        self.received.append(audio)
        if self.error is not None:
            raise self.error
        segments = [
            SimpleNamespace(
                start=0.0,
                end=0.8,
                text=" Synthetic first.",
                avg_logprob=-0.2,
                no_speech_prob=0.01,
                compression_ratio=1.0,
            ),
            SimpleNamespace(
                start=0.8,
                end=1.6,
                text=" Synthetic second.",
                avg_logprob=-0.4,
                no_speech_prob=0.02,
                compression_ratio=1.1,
            ),
        ]
        return iter(segments), SimpleNamespace(language="en", language_probability=0.95)


@pytest.fixture
def fake_model(registry):
    model = FakeModel()
    transcriber = FasterWhisperTranscriber()
    transcriber._model = lambda options: model
    for mime in ("audio/wav", "audio/mpeg", "audio/mp4"):
        registry.register(mime, AudioExtractor(transcriber))
    return model


def make_case(client) -> str:
    return client.post("/api/cases", json={"title": "Audio pipeline", "description": None}).json()[
        "id"
    ]


def upload_and_process(client, case_id, name, content) -> str:
    res = client.post(
        f"/api/cases/{case_id}/evidence",
        files={"file": (name, content, "application/octet-stream")},
    )
    assert res.status_code == 201, res.text
    evidence_id = res.json()["id"]
    client.post(f"/api/cases/{case_id}/evidence/{evidence_id}/process", json={})
    return evidence_id


def status_of(client, case_id, evidence_id) -> dict:
    return client.get(f"/api/cases/{case_id}/evidence/{evidence_id}/processing").json()


def test_wav_is_decoded_and_transcribed_with_timestamps(client, fake_model):
    case_id = make_case(client)
    evidence_id = upload_and_process(client, case_id, "call.wav", make_wav(2.0))

    state = status_of(client, case_id, evidence_id)
    assert state["status"] == "completed", state
    run = state["current_extraction"]
    assert run["extractor"] == "faster-whisper" and run["outcome"] == "ok"
    assert run["doc_metadata"]["duration_seconds"] == pytest.approx(2.0)
    assert run["doc_metadata"]["language"] == "en"

    [audio] = fake_model.received
    assert isinstance(audio, np.ndarray) and audio.dtype == np.float32 and len(audio) == 32000

    items = client.get(f"/api/cases/{case_id}/evidence/{evidence_id}/segments").json()["items"]
    assert [s["text"] for s in items] == ["Synthetic first.", "Synthetic second."]
    assert [(s["locator"]["start"], s["locator"]["end"]) for s in items] == [(0.0, 0.8), (0.8, 1.6)]
    assert [(s["t_start"], s["t_end"]) for s in items] == [(0.0, 0.8), (0.8, 1.6)]
    assert all(s["segment_type"] == "transcript_segment" for s in items)


def test_undecodable_wav_fails_as_corrupt_file(client, fake_model):
    case_id = make_case(client)
    # Passes the upload signature check (RIFF....WAVE) but has no playable audio.
    evidence_id = upload_and_process(client, case_id, "broken.wav", WAV_BYTES)

    state = status_of(client, case_id, evidence_id)
    assert state["status"] == "failed"
    assert state["error_code"] == "corrupt_file"
    assert state["error"] == "The audio file could not be decoded."
    assert fake_model.received == []  # the model was never asked to transcribe


def test_model_failure_is_an_internal_error_not_an_empty_success(client, registry):
    model = FakeModel(error=RuntimeError("engine failure"))
    transcriber = FasterWhisperTranscriber()
    transcriber._model = lambda options: model
    registry.register("audio/wav", AudioExtractor(transcriber))

    case_id = make_case(client)
    evidence_id = upload_and_process(client, case_id, "call.wav", make_wav(1.0))

    state = status_of(client, case_id, evidence_id)
    assert state["status"] == "failed"
    assert state["error_code"] == "internal_error"
    assert state["error"] == "Unexpected error during extraction."  # no engine message leaked
    assert state["has_current_extraction"] is False
