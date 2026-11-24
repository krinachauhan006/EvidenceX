"""Audio hardening: duration limit, timeout, model folder resolution, model errors.

No real model is loaded except in the two read-only lookups at the end, which only
check that the installed base and small models are found from any working directory.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.processing.errors import (
    ExtractionTimeoutError,
    LimitExceededError,
    ModelInitError,
    ModelInvalidError,
    ModelUnavailableError,
    ResourceExhaustedError,
)
from app.modules.processing.extractors import audio as audio_mod
from app.modules.processing.extractors.audio import (
    BACKEND_DIR,
    AudioExtractor,
    FasterWhisperTranscriber,
    classify_model_error,
    decode_audio_bytes,
    locate_model,
    resolve_model_dir,
)
from tests.fixtures.extraction import run
from tests.fixtures.processing_samples import make_wav
from tests.unit.test_audio_decoding import OPTIONS, RecordingModel, transcriber_with

# --- duration limit ---------------------------------------------------------------


def test_audio_within_the_limit_decodes():
    assert decode_audio_bytes(make_wav(2.0), max_seconds=2.0).duration == pytest.approx(2.0)


def test_audio_over_the_limit_is_rejected_with_a_limit_error():
    with pytest.raises(LimitExceededError) as info:
        decode_audio_bytes(make_wav(3.0), max_seconds=2.0)
    assert info.value.code == "limit_exceeded"
    assert "MAX_AUDIO_SECONDS" in info.value.message


def test_no_limit_means_no_limit():
    assert decode_audio_bytes(make_wav(3.0), max_seconds=None).duration == pytest.approx(3.0)


def test_over_limit_audio_never_loads_the_model():
    def must_not_load(options):
        raise AssertionError("the model must not be loaded for over-limit audio")

    transcriber = FasterWhisperTranscriber()
    transcriber._model = must_not_load
    with pytest.raises(LimitExceededError):
        transcriber.transcribe(make_wav(3.0), {**OPTIONS, "max_audio_seconds": 1})


def test_default_limits_are_documented_values():
    from app.core.config import Settings

    s = Settings()
    assert s.max_audio_seconds == 1200
    assert s.audio_timeout_seconds == 1800
    assert s.whisper_model_size == "base"  # the default model is unchanged


# --- timeout ----------------------------------------------------------------------


class Clock:
    """A controllable clock: each call returns the next value, then the last one."""

    def __init__(self, *values: float) -> None:
        self.values = list(values)

    def __call__(self) -> float:
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


def three_segments():
    return [
        SimpleNamespace(
            start=i,
            end=i + 1,
            text=f" Part {i}.",
            avg_logprob=-0.2,
            no_speech_prob=0.0,
            compression_ratio=1.0,
            words=None,
        )
        for i in range(3)
    ]


def test_timeout_during_transcription_raises_and_keeps_no_partial_text(monkeypatch):
    # start=0, after decode=1, first segment=2, second segment=100 (over the 10 s limit)
    monkeypatch.setattr(audio_mod, "_now", Clock(0.0, 1.0, 2.0, 100.0))
    model = RecordingModel(segments=three_segments())
    with pytest.raises(ExtractionTimeoutError) as info:
        transcriber_with(model).transcribe(make_wav(3.5), {**OPTIONS, "audio_timeout_seconds": 10})
    assert info.value.code == "timeout"
    assert "AUDIO_TIMEOUT_SECONDS" in info.value.message


def test_timeout_is_never_reported_as_an_empty_success(monkeypatch):
    monkeypatch.setattr(audio_mod, "_now", Clock(0.0, 1.0, 100.0))
    extractor = AudioExtractor(transcriber_with(RecordingModel(segments=three_segments())))
    with pytest.raises(ExtractionTimeoutError):
        run(extractor, make_wav(3.5), options={**OPTIONS, "audio_timeout_seconds": 10})


def test_timeout_during_decoding_stops_before_the_model(monkeypatch):
    monkeypatch.setattr(audio_mod, "_now", Clock(0.0, 50.0))

    def must_not_load(options):
        raise AssertionError("the model must not be loaded after a timeout")

    transcriber = FasterWhisperTranscriber()
    transcriber._model = must_not_load
    with pytest.raises(ExtractionTimeoutError):
        transcriber.transcribe(make_wav(0.5), {**OPTIONS, "audio_timeout_seconds": 10})


def test_within_the_timeout_all_segments_are_kept(monkeypatch):
    monkeypatch.setattr(audio_mod, "_now", Clock(0.0, 1.0, 2.0, 3.0, 4.0, 5.0))
    result = transcriber_with(RecordingModel(segments=three_segments())).transcribe(
        make_wav(3.5), {**OPTIONS, "audio_timeout_seconds": 10}
    )
    assert [s.text for s in result.segments] == [" Part 0.", " Part 1.", " Part 2."]


# --- model folder resolution --------------------------------------------------------


def test_backend_dir_is_the_backend_folder():
    assert (BACKEND_DIR / "app" / "main.py").is_file()


@pytest.mark.parametrize("cwd", ["tmp", "root", "app"])
def test_relative_model_dir_resolves_from_backend_not_the_working_directory(
    cwd, tmp_path, monkeypatch
):
    target = {"tmp": tmp_path, "root": Path(BACKEND_DIR.anchor), "app": BACKEND_DIR / "app"}
    monkeypatch.chdir(target[cwd])
    assert resolve_model_dir("./var/models") == (BACKEND_DIR / "var" / "models").resolve()
    assert resolve_model_dir(None) == (BACKEND_DIR / "var" / "models").resolve()


def test_absolute_model_dir_is_used_as_given(tmp_path):
    assert resolve_model_dir(str(tmp_path)) == tmp_path


def test_transcriber_uses_the_resolved_folder(tmp_path, monkeypatch):
    seen = {}

    def fake_locate(size, directory, allow):
        seen["directory"] = directory
        raise ModelUnavailableError("not here")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(audio_mod, "locate_model", fake_locate)
    monkeypatch.setattr(audio_mod, "_MODELS", {})  # ignore models loaded by other tests
    with pytest.raises(ModelUnavailableError):
        FasterWhisperTranscriber()._model({**OPTIONS, "whisper_model_dir": "./var/models"})
    assert seen["directory"] == str((BACKEND_DIR / "var" / "models").resolve())


_REAL_MODELS = BACKEND_DIR / "var" / "models"


@pytest.mark.parametrize("size", ["base", "small"])
def test_installed_models_are_found_from_any_working_directory(size, tmp_path, monkeypatch):
    folder = _REAL_MODELS / f"models--Systran--faster-whisper-{size}"
    if not folder.is_dir():
        pytest.skip(f"the '{size}' model is not installed")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")  # lookup only, never the network
    monkeypatch.chdir(tmp_path)
    path = locate_model(size, str(resolve_model_dir("./var/models")), allow_download=False)
    assert Path(path, "model.bin").is_file()
    assert Path(path).is_relative_to(folder)


# --- model error classification ---------------------------------------------------


def fake_cache(root: Path, size: str, files: dict[str, bytes]) -> None:
    """A minimal Hugging Face cache layout holding one snapshot."""
    repo = root / f"models--Systran--faster-whisper-{size}"
    snapshot = repo / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)
    (repo / "refs").mkdir()
    (repo / "refs" / "main").write_text("abc123")
    for name, content in files.items():
        (snapshot / name).write_bytes(content)


def test_missing_model_is_unavailable_and_names_the_download_command(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    with pytest.raises(ModelUnavailableError) as info:
        locate_model("base", str(tmp_path), allow_download=False)
    assert "fetch_whisper_model --size base" in info.value.message


def test_incomplete_model_folder_is_invalid_not_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    fake_cache(tmp_path, "base", {"config.json": b"{}"})  # no model.bin
    with pytest.raises(ModelInvalidError) as info:
        locate_model("base", str(tmp_path), allow_download=False)
    assert info.value.code == "model_invalid"
    assert "damaged" in info.value.message


def test_empty_model_file_is_invalid(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    fake_cache(tmp_path, "base", {"config.json": b"{}", "model.bin": b""})
    with pytest.raises(ModelInvalidError):
        locate_model("base", str(tmp_path), allow_download=False)


@pytest.mark.parametrize(
    "exc,expected",
    [
        (MemoryError(), ResourceExhaustedError),
        (RuntimeError("std::bad_alloc"), ResourceExhaustedError),
        (RuntimeError("CUDA out of memory"), ResourceExhaustedError),
        (RuntimeError("Unable to open file 'model.bin' in model 'x'"), ModelInvalidError),
        (ValueError("Unsupported model binary version"), ModelInvalidError),
        (RuntimeError("Unexpected end of file"), ModelInvalidError),
        (KeyError("something else"), ModelInitError),
        (RuntimeError("some unforeseen engine state"), ModelInitError),
    ],
)
def test_model_start_errors_are_classified(exc, expected):
    error = classify_model_error(exc, "small")
    assert isinstance(error, expected)


@pytest.mark.parametrize("exc", [MemoryError(), RuntimeError("Unable to open file"), KeyError("x")])
def test_only_a_missing_model_tells_the_user_to_download(exc):
    error = classify_model_error(exc, "small")
    if isinstance(error, ModelInvalidError):
        assert "download it again" in error.message  # damaged files: re-download is right
    else:
        assert "download" not in error.message.lower()
    assert "not available locally" not in error.message


def test_error_messages_do_not_echo_the_engine_message():
    error = classify_model_error(RuntimeError("SECRET-DETAIL-123 weird"), "base")
    assert "SECRET-DETAIL-123" not in error.message


def test_memory_failure_while_loading_is_reported_and_not_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    fake_cache(tmp_path, "base", {"config.json": b"{}", "model.bin": b"x"})

    def exploding_model(*args, **kwargs):
        raise RuntimeError("std::bad_alloc")

    import faster_whisper

    monkeypatch.setattr(faster_whisper, "WhisperModel", exploding_model)
    options = {**OPTIONS, "whisper_model_dir": str(tmp_path)}
    with pytest.raises(ResourceExhaustedError):
        FasterWhisperTranscriber()._model(options)
    assert not any(key[1] == str(tmp_path) for key in audio_mod._MODELS)


def test_memory_failure_during_transcription_is_a_resource_error():
    model = RecordingModel(error=MemoryError())
    with pytest.raises(ResourceExhaustedError):
        transcriber_with(model).transcribe(make_wav(0.5), OPTIONS)


def test_the_loader_passes_the_located_folder_to_the_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    fake_cache(tmp_path, "base", {"config.json": b"{}", "model.bin": b"x"})
    received = {}

    class FakeWhisper:
        def __init__(self, path, **kwargs):
            received["path"], received["kwargs"] = path, kwargs

    import faster_whisper

    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeWhisper)
    FasterWhisperTranscriber()._model({**OPTIONS, "whisper_model_dir": str(tmp_path)})
    assert os.path.isfile(os.path.join(received["path"], "model.bin"))
    assert received["kwargs"] == {"device": "cpu", "compute_type": "int8"}
    audio_mod._MODELS.clear()
