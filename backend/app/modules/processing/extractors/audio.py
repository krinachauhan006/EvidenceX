"""Audio extractor: machine transcription with timestamps (faster-whisper).

The transcript is machine output. It is not verified content and does not authenticate
the recording. Models are never downloaded implicitly: when the model is not present
locally the item fails with ``model_unavailable`` and the message names the explicit
download command.
"""

from __future__ import annotations

import gc
import io
import math
import os
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.modules.processing.errors import (
    CorruptFileError,
    DependencyMissingError,
    ExtractionError,
    ExtractionTimeoutError,
    LimitExceededError,
    ModelInitError,
    ModelInvalidError,
    ModelUnavailableError,
    ResourceExhaustedError,
)
from app.modules.processing.extractors.base import (
    ExtractionInput,
    ExtractionResult,
    ExtractionWarning,
    SegmentDraft,
)
from app.modules.processing.locators import AudioLocator

DOWNLOAD_COMMAND = "python -m app.tools.fetch_whisper_model"


@dataclass
class TranscribedWord:
    start: float
    end: float
    word: str
    probability: float | None = None  # engine-reported, 0..1


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    compression_ratio: float | None = None
    words: list[TranscribedWord] = field(default_factory=list)


@dataclass
class Transcription:
    segments: list[TranscriptSegment]
    duration: float | None = None
    language: str | None = None
    language_probability: float | None = None
    model: str = ""
    device: str = ""
    compute_type: str = ""
    engine: str = "faster-whisper"
    engine_version: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class Transcriber(Protocol):
    def transcribe(self, data: bytes, options: Mapping[str, Any]) -> Transcription: ...


def probability_from_logprob(avg_logprob: float | None) -> float | None:
    """exp(avg_logprob) clamped to 0..1, or None when the engine gave no value."""
    if avg_logprob is None or math.isnan(avg_logprob):
        return None
    return max(0.0, min(1.0, math.exp(avg_logprob)))


# --- audio decoding --------------------------------------------------------------
#
# EvidenceX decodes audio itself and hands faster-whisper a ready-made array. Passing
# raw bytes would make faster-whisper call its own decoder, which uses an ``av.open``
# keyword (``metadata_errors``) that the installed PyAV no longer accepts. Given a
# NumPy array, ``WhisperModel.transcribe`` skips that decoder entirely.

WHISPER_SAMPLE_RATE = 16_000
# Stop after this many undecodable frames in a row: the stream is not usable.
_MAX_CONSECUTIVE_BAD_FRAMES = 1_000


@dataclass(frozen=True)
class DecodedAudio:
    """Mono float32 samples in [-1, 1) at ``sample_rate``."""

    samples: Any  # numpy.ndarray, 1-D, float32
    sample_rate: int
    skipped_frames: int = 0

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate


def decode_audio_bytes(
    data: bytes, sample_rate: int = WHISPER_SAMPLE_RATE, max_seconds: float | None = None
) -> DecodedAudio:
    """Decode an uploaded audio file to mono float32 samples with PyAV.

    Undecodable input raises ``CorruptFileError``. Audio longer than ``max_seconds``
    raises ``LimitExceededError`` as soon as the limit is passed, so an over-long file
    is never fully decoded into memory. Programming errors (for example a ``TypeError``
    from an API mismatch) are not caught, so they surface as internal errors instead
    of being reported as a bad file. Nothing about the content is logged or put into
    error messages.
    """
    max_samples = int(max_seconds * sample_rate) if max_seconds else None
    try:
        import av
        import numpy as np
        from av.audio.resampler import AudioResampler
    except ImportError as exc:
        raise DependencyMissingError(
            "PyAV and NumPy are required for audio. Install them with: pip install av numpy"
        ) from exc

    if not data:
        raise CorruptFileError("The audio file is empty.")

    chunks: list[Any] = []
    skipped = 0
    total = 0
    try:
        with av.open(io.BytesIO(data), mode="r") as container:
            if not container.streams.audio:
                raise CorruptFileError("The file contains no audio stream.")
            resampler = AudioResampler(format="s16", layout="mono", rate=sample_rate)
            frames = container.decode(audio=0)
            bad_in_a_row = 0
            while True:
                try:
                    frame = next(frames)
                except StopIteration:
                    break
                except av.error.InvalidDataError:
                    # Skip a damaged frame, as faster-whisper's own decoder does, but
                    # count it so the result can say so.
                    skipped += 1
                    bad_in_a_row += 1
                    if bad_in_a_row > _MAX_CONSECUTIVE_BAD_FRAMES:
                        raise CorruptFileError("The audio stream could not be decoded.") from None
                    continue
                bad_in_a_row = 0
                for out in resampler.resample(frame):
                    chunks.append(out.to_ndarray().reshape(-1))
                    total += chunks[-1].size
                if max_samples is not None and total > max_samples:
                    raise LimitExceededError(
                        f"The recording is longer than the {max_seconds:g}-second limit "
                        "(MAX_AUDIO_SECONDS). It was not transcribed."
                    )
            for out in resampler.resample(None):  # flush buffered samples
                chunks.append(out.to_ndarray().reshape(-1))
                total += chunks[-1].size
            if max_samples is not None and total > max_samples:
                raise LimitExceededError(
                    f"The recording is longer than the {max_seconds:g}-second limit "
                    "(MAX_AUDIO_SECONDS). It was not transcribed."
                )
            del resampler
    except ExtractionError:
        raise
    except (av.error.FFmpegError, ValueError, IndexError, EOFError, OSError) as exc:
        raise CorruptFileError("The audio file could not be decoded.") from exc
    finally:
        # PyAV resampler objects are only released reliably after a collection (the
        # same workaround faster-whisper uses).
        gc.collect()

    if not chunks:
        raise CorruptFileError("The audio file contains no decodable audio.")
    pcm = np.concatenate(chunks)
    if pcm.size == 0:
        raise CorruptFileError("The audio file contains no decodable audio.")
    samples = pcm.astype(np.float32) / 32768.0
    return DecodedAudio(samples=samples, sample_rate=sample_rate, skipped_frames=skipped)


# --- model location and load errors ----------------------------------------------

# backend/ (this file is backend/app/modules/processing/extractors/audio.py)
BACKEND_DIR = Path(__file__).resolve().parents[4]
_MODEL_FILES = ("model.bin", "config.json")
# Words that ctranslate2/tokenizers use for allocation failures and for unreadable or
# malformed model files. Only used to classify; the message itself is never stored.
_MEMORY_HINTS = ("bad_alloc", "bad alloc", "out of memory", "cannot allocate", "alloc")
_INVALID_HINTS = (
    "unable to open",
    "failed to open",
    "invalid",
    "corrupt",
    "unexpected end",
    "parse",
    "unsupported model",
    "magic",
    "format",
    "truncated",
)


def resolve_model_dir(value: Any) -> Path:
    """The model directory as an absolute path.

    A relative ``WHISPER_MODEL_DIR`` (the default is ``./var/models``) is resolved from
    the backend folder, never from the current working directory, so the backend and
    tools find the same models wherever they are started from.
    """
    path = Path(str(value or "./var/models")).expanduser()
    return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


def locate_model(size: str, directory: str, allow_download: bool) -> str:
    """Return the local folder holding the model, or raise a specific error.

    Offline by default: nothing is fetched unless ``allow_download`` is set.
    """
    try:
        from faster_whisper.utils import download_model

        path = download_model(size, local_files_only=not allow_download, cache_dir=directory)
    except Exception as exc:  # noqa: BLE001 - every lookup failure means "not on disk"
        raise ModelUnavailableError(
            f"The speech model '{size}' is not available locally. Download it "
            f"with: {DOWNLOAD_COMMAND} --size {size}"
        ) from exc
    missing = [name for name in _MODEL_FILES if not os.path.isfile(os.path.join(path, name))]
    if missing or os.path.getsize(os.path.join(path, "model.bin")) == 0:
        raise ModelInvalidError(
            f"The speech model '{size}' is on disk but incomplete or damaged. Delete its "
            f"folder and download it again with: {DOWNLOAD_COMMAND} --size {size}"
        )
    return path


def classify_model_error(exc: BaseException, size: str) -> ExtractionError:
    """Map an exception raised while starting the model to a precise error.

    Memory and corruption problems are never reported as "download the model".
    """
    if isinstance(exc, MemoryError):
        return _resource_error(size)
    text = str(exc).lower()
    if any(hint in text for hint in _MEMORY_HINTS):
        return _resource_error(size)
    if isinstance(exc, (ValueError, OSError, RuntimeError)) and any(
        hint in text for hint in _INVALID_HINTS
    ):
        return ModelInvalidError(
            f"The speech model '{size}' could not be read. Its files may be damaged. "
            f"Delete its folder and download it again with: {DOWNLOAD_COMMAND} --size {size}"
        )
    return ModelInitError(
        f"The speech model '{size}' could not be started ({type(exc).__name__}). "
        "Check the backend log; the model files themselves were found."
    )


def _resource_error(size: str) -> ResourceExhaustedError:
    return ResourceExhaustedError(
        f"Not enough memory to run the speech model '{size}'. Close other programs, "
        "process the file again, or use a smaller model (WHISPER_MODEL_SIZE)."
    )


_MODEL_LOCK = threading.Lock()
_MODELS: dict[tuple[str, str, str, str, bool], Any] = {}


class FasterWhisperTranscriber:
    """Default engine. Heavy imports and the model load happen on first use."""

    def _model(self, options: Mapping[str, Any]) -> Any:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise DependencyMissingError(
                "faster-whisper is not installed. Install it with: pip install faster-whisper"
            ) from exc
        size = str(options.get("whisper_model_size") or "base")
        directory = str(resolve_model_dir(options.get("whisper_model_dir")))
        device = str(options.get("whisper_device") or "cpu")
        compute = str(options.get("whisper_compute_type") or "int8")
        allow = bool(options.get("whisper_allow_download", False))
        key = (size, directory, device, compute, allow)
        with _MODEL_LOCK:
            if key not in _MODELS:
                model_path = locate_model(size, directory, allow)
                try:
                    _MODELS[key] = WhisperModel(model_path, device=device, compute_type=compute)
                except Exception as exc:  # noqa: BLE001 - classified below
                    raise classify_model_error(exc, size) from exc
            return _MODELS[key]

    def transcribe(self, data: bytes, options: Mapping[str, Any]) -> Transcription:
        # Decode first: a bad file fails as corrupt_file without loading the model.
        started = _now()
        timeout = float(options.get("audio_timeout_seconds") or 0) or None
        max_seconds = float(options.get("max_audio_seconds") or 0) or None
        decoded = decode_audio_bytes(data, max_seconds=max_seconds)  # before any model work
        _check_deadline(started, timeout)
        model = self._model(options)
        language = str(options.get("whisper_language") or "") or None
        word_timestamps = bool(options.get("whisper_word_timestamps", True))
        prompt = str(options.get("whisper_initial_prompt") or "").strip() or None
        try:
            iterator, info = model.transcribe(
                decoded.samples,  # an array, so faster-whisper never runs its own decoder
                language=language,
                vad_filter=bool(options.get("whisper_vad_filter", True)),
                word_timestamps=word_timestamps,
                initial_prompt=prompt,
            )
            segments: list[TranscriptSegment] = []
            # The engine yields segments lazily, one ~30 s window at a time, so the
            # deadline is checked between windows. A timeout raises: it is never
            # turned into a shorter "successful" transcript.
            for s in iterator:
                _check_deadline(started, timeout)
                segments.append(
                    TranscriptSegment(
                        start=float(s.start),
                        end=float(s.end),
                        text=str(s.text),
                        avg_logprob=getattr(s, "avg_logprob", None),
                        no_speech_prob=getattr(s, "no_speech_prob", None),
                        compression_ratio=getattr(s, "compression_ratio", None),
                        words=[
                            TranscribedWord(
                                start=float(w.start),
                                end=float(w.end),
                                word=str(w.word),
                                probability=getattr(w, "probability", None),
                            )
                            for w in (getattr(s, "words", None) or [])
                        ],
                    )
                )
            _check_deadline(started, timeout)
        except ExtractionError:
            raise
        except MemoryError as exc:
            raise _resource_error(str(options.get("whisper_model_size") or "base")) from exc
        except Exception as exc:  # noqa: BLE001
            if _is_decode_error(exc):
                raise CorruptFileError("The audio file could not be decoded.") from exc
            raise
        return Transcription(
            segments=segments,
            duration=decoded.duration,
            language=getattr(info, "language", None),
            language_probability=getattr(info, "language_probability", None),
            model=str(options.get("whisper_model_size") or "base"),
            device=str(options.get("whisper_device") or "cpu"),
            compute_type=str(options.get("whisper_compute_type") or "int8"),
            engine_version=_engine_version(),
            extra={
                "skipped_frames": decoded.skipped_frames,
                "word_timestamps": word_timestamps,
                "initial_prompt_used": prompt is not None,
            },
        )


_now = time.monotonic  # module-level so tests can substitute a controlled clock


def _check_deadline(started: float, timeout: float | None) -> None:
    if timeout is not None and _now() - started > timeout:
        raise ExtractionTimeoutError(
            f"Transcription took longer than the {timeout:g}-second limit "
            "(AUDIO_TIMEOUT_SECONDS) and was stopped. No partial transcript was saved."
        )


def _engine_version() -> str:
    try:
        import importlib.metadata as md

        return md.version("faster-whisper")
    except Exception:  # noqa: BLE001
        return ""


def _is_decode_error(exc: Exception) -> bool:
    module = type(exc).__module__
    return (
        module.startswith("av")
        or isinstance(exc, (EOFError, ValueError))
        and "decode" in str(exc).lower()
    )


class AudioExtractor:
    name = "faster-whisper"
    version = "1"

    def __init__(self, transcriber: Transcriber | None = None) -> None:
        self._transcriber: Transcriber = transcriber or FasterWhisperTranscriber()

    def extract(self, inp: ExtractionInput) -> ExtractionResult:
        result = self._transcriber.transcribe(inp.data, inp.options)
        duration = result.duration
        low_threshold = float(inp.options.get("whisper_low_word_probability", 0.5))
        warnings: list[ExtractionWarning] = []
        segments: list[SegmentDraft] = []
        total_chars = 0
        truncated = False
        clamped = 0
        low_words_total = 0

        def bound(start: float, end: float) -> tuple[float, float]:
            """Limit a span to [0, duration] of the recording. Times inside it are kept."""
            nonlocal clamped
            s, e = max(0.0, float(start)), float(end)
            if duration is not None:
                s, e = min(s, duration), min(e, duration)
            e = max(s, e)
            if (s, e) != (float(start), float(end)):
                clamped += 1
            return s, e

        for item in result.segments:
            text = item.text.strip()  # raw engine text; nothing is corrected or normalized
            if not text:
                continue
            if total_chars + len(text) > inp.limits.max_extracted_chars:
                truncated = True
                break
            total_chars += len(text)
            start, end = bound(item.start, item.end)
            data: dict[str, Any] = {
                "avg_logprob": item.avg_logprob,
                "no_speech_prob": item.no_speech_prob,
                "compression_ratio": item.compression_ratio,
                "source": "machine_transcription",
            }
            if item.words:
                words = []
                for w in item.words:
                    w_start, w_end = bound(w.start, w.end)
                    words.append(
                        {
                            "word": w.word.strip(),
                            "start": w_start,
                            "end": w_end,
                            "probability": w.probability,  # as reported by the engine
                        }
                    )
                low = [
                    w["word"]
                    for w in words
                    if w["probability"] is not None and w["probability"] < low_threshold
                ]
                data["words"] = words
                data["low_probability_words"] = low
                low_words_total += len(low)
            segments.append(
                SegmentDraft(
                    segment_type="transcript_segment",
                    text=text,
                    locator=AudioLocator(start=start, end=end),
                    data=data,
                    engine_confidence=probability_from_logprob(item.avg_logprob),
                    language=result.language,
                )
            )
        if clamped:
            warnings.append(
                ExtractionWarning(
                    "timestamps_clamped",
                    f"{clamped} engine timestamp(s) fell outside the recording and were "
                    "limited to its start or end.",
                    {"count": clamped, "duration_seconds": duration},
                )
            )
        if low_words_total:
            warnings.append(
                ExtractionWarning(
                    "low_probability_words",
                    f"{low_words_total} word(s) have an engine-reported probability below "
                    f"{low_threshold}. They may be misheard; check them against the audio.",
                    {"count": low_words_total, "threshold": low_threshold},
                )
            )
        if result.extra.get("initial_prompt_used"):
            warnings.append(
                ExtractionWarning(
                    "initial_prompt_used",
                    "A configured prompt biased the speech engine. It can change which "
                    "words are recognized, including meaning. Treat the text with care.",
                )
            )
        skipped_frames = int(result.extra.get("skipped_frames") or 0)
        if skipped_frames:
            warnings.append(
                ExtractionWarning(
                    "audio_frames_skipped",
                    f"{skipped_frames} damaged audio frame(s) could not be decoded and were "
                    "skipped. The transcript may have gaps there.",
                    {"count": skipped_frames},
                )
            )
        if truncated:
            warnings.append(
                ExtractionWarning(
                    "char_limit_reached",
                    "Extraction stopped because the total text limit was reached.",
                    {"limit": inp.limits.max_extracted_chars},
                )
            )
        if not segments:
            outcome = "empty"
            warnings.append(
                ExtractionWarning("no_speech_detected", "No speech was detected in the audio.")
            )
        else:
            outcome = "partial" if truncated else "ok"
        metadata = {
            "transcription": "machine",
            "duration_seconds": result.duration,
            "language": result.language,
            "language_probability": result.language_probability,
            "model": result.model,
            "device": result.device,
            "compute_type": result.compute_type,
            "engine": result.engine,
            "segment_count": len(segments),
            "word_timestamps": bool(result.extra.get("word_timestamps", False)),
            "initial_prompt_used": bool(result.extra.get("initial_prompt_used", False)),
            "low_word_probability_threshold": low_threshold,
        }
        return ExtractionResult(
            self.name, result.engine_version or self.version, outcome, segments, metadata, warnings
        )
