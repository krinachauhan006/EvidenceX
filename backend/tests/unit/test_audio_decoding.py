"""Audio decoding with the installed PyAV, and how the decoded array reaches the model.

Regression tests for the faster-whisper 1.2.1 / PyAV 19 incompatibility: faster-whisper's
own decoder calls ``av.open(..., metadata_errors="ignore")``, which PyAV 19 rejects with
a TypeError. EvidenceX now decodes the audio itself and passes a NumPy array, so that
decoder is never used.

All audio here is generated. No model is loaded except in the last test, which is
skipped unless a local model already exists, and nothing is downloaded.
"""

from __future__ import annotations

import io
import math
import os
import struct
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from app.modules.processing.errors import CorruptFileError
from app.modules.processing.extractors.audio import (
    WHISPER_SAMPLE_RATE,
    AudioExtractor,
    DecodedAudio,
    FasterWhisperTranscriber,
    Transcription,
    decode_audio_bytes,
)
from tests.fixtures.extraction import assert_locators_valid, run, warning_codes
from tests.fixtures.fake_engines import FakeTranscriber
from tests.fixtures.processing_samples import make_pdf_text, make_wav
from tests.fixtures.sample_files import PNG_BYTES, WAV_BYTES


def make_wav_custom(seconds: float, *, rate: int, channels: int, amplitude: int = 12000) -> bytes:
    frames = bytearray()
    for n in range(int(seconds * rate)):
        sample = int(amplitude * math.sin(2 * math.pi * 440 * n / rate))
        frames += struct.pack("<h", sample) * channels
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(bytes(frames))
    return buf.getvalue()


def header_only_wav() -> bytes:
    """A structurally valid WAV with zero audio frames."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"")
    return buf.getvalue()


# --- decoding with the real installed PyAV --------------------------------------


def test_valid_wav_decodes_to_mono_16k_float32():
    decoded = decode_audio_bytes(make_wav(1.0))
    assert isinstance(decoded, DecodedAudio)
    assert isinstance(decoded.samples, np.ndarray)
    assert decoded.samples.dtype == np.float32
    assert decoded.samples.ndim == 1
    assert decoded.sample_rate == WHISPER_SAMPLE_RATE == 16000
    assert decoded.skipped_frames == 0


def test_duration_comes_from_the_decoded_sample_count():
    decoded = decode_audio_bytes(make_wav(1.5))
    assert len(decoded.samples) == 24000
    assert decoded.duration == pytest.approx(1.5)
    assert decoded.duration == len(decoded.samples) / decoded.sample_rate


def test_stereo_44k_is_downmixed_and_resampled():
    decoded = decode_audio_bytes(make_wav_custom(0.5, rate=44100, channels=2))
    assert decoded.samples.ndim == 1
    assert decoded.sample_rate == 16000
    # Resampling can add or drop a few samples at the edges; the length is ~8000.
    assert abs(len(decoded.samples) - 8000) <= 64
    assert decoded.duration == pytest.approx(0.5, abs=0.01)


def test_8k_input_is_upsampled_to_16k():
    decoded = decode_audio_bytes(make_wav_custom(1.0, rate=8000, channels=1))
    assert abs(len(decoded.samples) - 16000) <= 64


def test_sample_values_are_scaled_into_minus_one_to_one():
    decoded = decode_audio_bytes(make_wav(0.5))
    assert float(np.max(np.abs(decoded.samples))) < 1.0
    # A 12000/32768 amplitude tone peaks near 0.37.
    assert float(np.max(np.abs(decoded.samples))) == pytest.approx(12000 / 32768, abs=0.02)


def test_silent_audio_decodes_to_zeros_not_an_error():
    decoded = decode_audio_bytes(make_wav(0.5, silent=True))
    assert len(decoded.samples) == 8000
    assert float(np.max(np.abs(decoded.samples))) == 0.0


def test_decoding_does_not_use_faster_whispers_decoder(monkeypatch):
    import faster_whisper.audio

    def forbidden(*args, **kwargs):
        raise AssertionError("faster_whisper.audio.decode_audio must not be called")

    monkeypatch.setattr(faster_whisper.audio, "decode_audio", forbidden)
    decode_audio_bytes(make_wav(0.2))


def test_the_incompatible_keyword_is_really_rejected_by_installed_pyav():
    """Documents why the workaround exists. If this starts failing, PyAV accepts the
    keyword again and the workaround is no longer strictly needed (it stays harmless)."""
    import av

    with pytest.raises(TypeError, match="metadata_errors"):
        av.open(io.BytesIO(make_wav(0.1)), mode="r", metadata_errors="ignore")


# --- bad input ------------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not audio at all",
        os.urandom(4096),
        WAV_BYTES,  # RIFF/WAVE signature only, no real format chunk
        make_wav(1.0)[:30],  # truncated inside the header
        header_only_wav(),  # valid container, zero samples
        PNG_BYTES,
        make_pdf_text(1),
    ],
    ids=["empty", "text", "random", "signature-only", "truncated", "no-samples", "png", "pdf"],
)
def test_undecodable_audio_raises_corrupt_file(data):
    with pytest.raises(CorruptFileError) as info:
        decode_audio_bytes(data)
    assert info.value.code == "corrupt_file"


def test_corrupt_file_message_does_not_echo_file_content():
    secret = b"SECRET-CONTENT-12345 " * 50
    with pytest.raises(CorruptFileError) as info:
        decode_audio_bytes(secret)
    assert "SECRET" not in info.value.message


# --- the transcriber hands the model an array -----------------------------------


class RecordingModel:
    """Stands in for WhisperModel. Records what transcribe() receives."""

    def __init__(self, segments=None, info=None, error: Exception | None = None):
        self.calls: list[dict] = []
        self._segments = (
            segments
            if segments is not None
            else [
                SimpleNamespace(
                    start=0.0,
                    end=1.2,
                    text=" Synthetic words. ",
                    avg_logprob=-0.3,
                    no_speech_prob=0.02,
                    compression_ratio=1.1,
                )
            ]
        )
        # A deliberately wrong duration: the transcriber must use the decoded one.
        self._info = info or SimpleNamespace(
            language="en", language_probability=0.97, duration=999.0
        )
        self._error = error

    def transcribe(self, audio, **kwargs):
        self.calls.append({"audio": audio, **kwargs})
        if self._error is not None:
            raise self._error
        return iter(self._segments), self._info


def transcriber_with(model) -> FasterWhisperTranscriber:
    transcriber = FasterWhisperTranscriber()
    transcriber._model = lambda options: model  # no real model is loaded
    return transcriber


OPTIONS = {
    "whisper_model_size": "base",
    "whisper_device": "cpu",
    "whisper_compute_type": "int8",
    "whisper_language": "",
    "whisper_vad_filter": True,
}


def test_model_receives_a_float32_numpy_array_not_bytes():
    model = RecordingModel()
    transcriber_with(model).transcribe(make_wav(1.0), OPTIONS)
    audio = model.calls[0]["audio"]
    assert isinstance(audio, np.ndarray)
    assert not isinstance(audio, (bytes, bytearray, io.IOBase))
    assert audio.dtype == np.float32 and audio.ndim == 1
    assert len(audio) == 16000


def test_transcription_options_are_preserved():
    model = RecordingModel()
    transcriber_with(model).transcribe(make_wav(0.5), {**OPTIONS, "whisper_language": "de"})
    call = model.calls[0]
    assert call["language"] == "de"
    assert call["vad_filter"] is True
    assert call["word_timestamps"] is True  # default since the transcription benchmark
    assert call["initial_prompt"] is None  # no prompt unless configured

    model = RecordingModel()
    transcriber_with(model).transcribe(
        make_wav(0.5), {**OPTIONS, "whisper_language": "", "whisper_vad_filter": False}
    )
    assert model.calls[0]["language"] is None  # empty means auto-detect
    assert model.calls[0]["vad_filter"] is False


def test_transcription_result_structure_and_decoded_duration():
    result = transcriber_with(RecordingModel()).transcribe(make_wav(1.5), OPTIONS)
    assert isinstance(result, Transcription)
    assert result.duration == pytest.approx(1.5)  # from samples, not the engine's 999
    assert result.language == "en" and result.language_probability == 0.97
    assert (result.model, result.device, result.compute_type) == ("base", "cpu", "int8")
    assert result.extra == {
        "skipped_frames": 0,
        "word_timestamps": True,
        "initial_prompt_used": False,
    }
    [segment] = result.segments
    assert (segment.start, segment.end) == (0.0, 1.2)
    assert segment.text == " Synthetic words. "
    assert segment.avg_logprob == -0.3


def test_corrupt_audio_fails_before_the_model_is_touched():
    def must_not_load(options):
        raise AssertionError("the model must not be loaded for an undecodable file")

    transcriber = FasterWhisperTranscriber()
    transcriber._model = must_not_load
    with pytest.raises(CorruptFileError):
        transcriber.transcribe(b"not audio", OPTIONS)


def test_model_failures_propagate_and_are_not_turned_into_an_empty_transcript():
    model = RecordingModel(error=RuntimeError("engine exploded"))
    with pytest.raises(RuntimeError):
        transcriber_with(model).transcribe(make_wav(0.5), OPTIONS)


def test_errors_while_iterating_segments_also_propagate():
    def broken_segments():
        yield SimpleNamespace(start=0.0, end=1.0, text="first")
        raise RuntimeError("decoder state lost")

    model = RecordingModel()
    model.transcribe = lambda audio, **kw: (broken_segments(), model._info)
    with pytest.raises(RuntimeError):
        transcriber_with(model).transcribe(make_wav(0.5), OPTIONS)


# --- AudioExtractor output stays compatible -------------------------------------


def test_extractor_output_with_the_real_decoder_and_a_fake_model():
    # 1.5 s of audio so the fake 0.0-1.2 s segment lies inside the recording.
    result = run(
        AudioExtractor(transcriber_with(RecordingModel())), make_wav(1.5), mime="audio/wav"
    )
    assert result.outcome == "ok"
    assert [s.segment_type for s in result.segments] == ["transcript_segment"]
    segment = result.segments[0]
    assert segment.text == "Synthetic words."
    assert (segment.locator.start, segment.locator.end) == (0.0, 1.2)
    assert segment.data["source"] == "machine_transcription"
    assert segment.engine_confidence == pytest.approx(math.exp(-0.3))
    assert result.metadata["duration_seconds"] == pytest.approx(1.5)
    assert result.metadata["transcription"] == "machine"
    assert set(result.metadata) == {
        "transcription",
        "duration_seconds",
        "language",
        "language_probability",
        "model",
        "device",
        "compute_type",
        "engine",
        "segment_count",
        "word_timestamps",
        "initial_prompt_used",
        "low_word_probability_threshold",
    }
    assert_locators_valid(result)


def test_no_speech_from_the_model_is_still_empty_not_failed():
    result = run(AudioExtractor(transcriber_with(RecordingModel(segments=[]))), make_wav(0.5))
    assert result.outcome == "empty"
    assert "no_speech_detected" in warning_codes(result)


def test_skipped_frames_are_reported_as_a_warning():
    fake = FakeTranscriber()
    original = fake.transcribe

    def with_skips(data, options):
        result = original(data, options)
        result.extra = {"skipped_frames": 3}
        return result

    fake.transcribe = with_skips
    result = run(AudioExtractor(fake), make_wav(0.5))
    detail = next(w.detail for w in result.warnings if w.code == "audio_frames_skipped")
    assert detail == {"count": 3}


def test_fake_transcriber_results_have_no_skip_warning():
    assert "audio_frames_skipped" not in warning_codes(run(AudioExtractor(FakeTranscriber()), b""))


# --- real model (skipped unless the model is already on disk) --------------------

_MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "var", "models")
_HAS_LOCAL_MODEL = os.path.isdir(os.path.join(_MODEL_DIR, "models--Systran--faster-whisper-base"))


@pytest.mark.skipif(not _HAS_LOCAL_MODEL, reason="no local faster-whisper 'base' model")
def test_real_model_transcribes_decoded_audio_without_the_pyav_type_error(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")  # never reach the network
    result = run(
        AudioExtractor(),
        make_wav(1.0),
        mime="audio/wav",
        options={
            "whisper_model_size": "base",
            "whisper_model_dir": os.path.abspath(_MODEL_DIR),
            "whisper_device": "cpu",
            "whisper_compute_type": "int8",
            "whisper_allow_download": False,
            "whisper_vad_filter": True,
        },
    )
    # A pure tone contains no speech. The point is that the real engine runs end to end.
    assert result.outcome in {"empty", "ok"}
    assert result.metadata["duration_seconds"] == pytest.approx(1.0)
    assert result.metadata["model"] == "base"
