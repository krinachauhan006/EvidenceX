"""Turn a browser-submitted engine result into the same ``ExtractionResult`` the
server-side extractors produce, after checking it.

Pure functions: no database, storage or HTTP. The service passes in what the server
itself knows about the file (``ServerFacts``: image size, WAV duration) so a result
that does not fit the stored file is refused.

What is checked (the browser is not trusted):

* every number is finite; boxes are ordered and lie inside the image or frame (a
  rounding overshoot of up to ``EDGE_TOLERANCE_PX`` is clamped, more is refused);
* times lie inside the recording (up to ``EDGE_TOLERANCE_SECONDS`` is clamped) and
  ``end >= start``; video frames are within the video and in time order;
* the reported image size equals the stored image's size, and a WAV's duration
  matches the stored file, when the server can read them;
* text is stripped of NUL and other control characters (never otherwise changed),
  and the total stays within MAX_EXTRACTED_CHARS.

Segment shapes mirror ``extractors/image_ocr.py``, ``audio.py`` and ``video.py``:
``ocr_line`` + ImageLocator, ``transcript_segment`` + AudioLocator, ``video_frame`` and
``video_ocr_line`` + VideoLocator. Engine confidence is the engine's own figure (mean
word confidence for OCR); Transformers.js Whisper reports none, so transcript segments
carry ``None`` rather than an invented value.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.modules.processing.browser_schemas import (
    BrowserAudioResultIn,
    BrowserEngineIn,
    BrowserImageResultIn,
    BrowserOcrLineIn,
    BrowserTranscriptSegmentIn,
    BrowserVideoResultIn,
)
from app.modules.processing.extractors.base import (
    ExtractionResult,
    ExtractionWarning,
    SegmentDraft,
)
from app.modules.processing.locators import AudioLocator, ImageLocator, VideoLocator

EDGE_TOLERANCE_PX = 2.0
EDGE_TOLERANCE_SECONDS = 1.0
# A WAV whose reported duration differs from the stored file by more than this is not
# the file that was processed.
DURATION_TOLERANCE_SECONDS = 1.0
MIN_VIDEO_LINE_CHARS = 2  # as in extractors/video.py

IMAGE_EXTRACTOR = "browser-tesseract.js"
AUDIO_EXTRACTOR = "browser-whisper"
VIDEO_EXTRACTOR = "browser-video"
VIDEO_EXTRACTOR_VERSION = "1"

# Control characters except tab and newline (NUL cannot be stored in PostgreSQL text).
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class BrowserResultError(ValueError):
    """The submitted result does not fit the stored file or the limits."""


@dataclass(frozen=True)
class ServerFacts:
    """What the server read from the stored file itself (None = could not tell)."""

    image_size: tuple[int, int] | None = None  # (width, height) after EXIF orientation
    audio_duration: float | None = None


def _browser_warning(engine: str) -> ExtractionWarning:
    return ExtractionWarning(
        "processed_in_browser",
        f"Machine output from {engine}, run in the uploader's browser. The server checked "
        "that every position fits the stored file, but did not run the engine itself.",
    )


def clean_text(value: str) -> str:
    return _CONTROL.sub("", value).strip()


def _finite(*values: float) -> None:
    if not all(math.isfinite(v) for v in values):
        raise BrowserResultError("a position or time is not a finite number")


def check_bbox(bbox: Sequence[float], width: int, height: int) -> tuple[float, float, float, float]:
    """An ordered box inside ``width`` x ``height``; small overshoots are clamped."""
    x0, y0, x1, y1 = (float(v) for v in bbox)
    _finite(x0, y0, x1, y1)
    if x1 < x0 or y1 < y0:
        raise BrowserResultError("a text box has its corners in the wrong order")
    tol = EDGE_TOLERANCE_PX
    if x0 < -tol or y0 < -tol or x1 > width + tol or y1 > height + tol:
        raise BrowserResultError("a text box lies outside the image")
    return (
        round(min(max(x0, 0.0), width), 2),
        round(min(max(y0, 0.0), height), 2),
        round(min(max(x1, 0.0), width), 2),
        round(min(max(y1, 0.0), height), 2),
    )


def check_span(start: float, end: float, duration: float) -> tuple[float, float, bool]:
    """(start, end, clamped) inside ``[0, duration]``."""
    _finite(start, end)
    if end < start:
        raise BrowserResultError("a transcript segment ends before it starts")
    if end > duration + EDGE_TOLERANCE_SECONDS:
        raise BrowserResultError("a transcript segment lies beyond the end of the recording")
    s, e = min(start, duration), min(end, duration)
    return round(s, 3), round(e, 3), (s, e) != (start, end)


@dataclass
class _Line:
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float | None
    words: list[dict[str, Any]]


def _lines(lines: Sequence[BrowserOcrLineIn], width: int, height: int) -> list[_Line]:
    """Validated OCR lines, grouped as the server's ``group_words_into_lines`` does:
    empty words are dropped and the line confidence is the mean word confidence."""
    out: list[_Line] = []
    for line in lines:
        text = clean_text(line.text)
        if not text:
            continue
        words: list[dict[str, Any]] = []
        for w in line.words:
            wt = clean_text(w.text)
            if not wt:
                continue
            _finite(w.confidence)
            words.append(
                {
                    "text": wt,
                    "bbox": list(check_bbox(w.bbox, width, height)),
                    "confidence": round(float(w.confidence), 4),
                }
            )
        if words:
            confidence: float | None = sum(w["confidence"] for w in words) / len(words)
        else:
            confidence = line.confidence
        out.append(
            _Line(
                text=text,
                bbox=check_bbox(line.bbox, width, height),
                confidence=None if confidence is None else round(confidence, 4),
                words=words,
            )
        )
    return out


def _check_chars(segments: Sequence[SegmentDraft], max_chars: int) -> None:
    if sum(len(s.text or "") for s in segments) > max_chars:
        raise BrowserResultError("the result has more text than this server accepts")


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


# --- image -----------------------------------------------------------------------------


def build_image_result(
    payload: BrowserImageResultIn,
    engine: BrowserEngineIn,
    facts: ServerFacts,
    *,
    min_confidence: float,
    max_chars: int,
) -> ExtractionResult:
    width, height = payload.width, payload.height
    if facts.image_size is not None and facts.image_size != (width, height):
        raise BrowserResultError("the reported image size does not match the stored image")
    language = payload.language
    lines = _lines(payload.lines, width, height)
    segments = [
        SegmentDraft(
            segment_type="ocr_line",
            text=ln.text,
            locator=ImageLocator(bbox=ln.bbox, width=width, height=height),
            data={"words": ln.words},
            engine_confidence=ln.confidence,
            language=language,
        )
        for ln in lines
    ]
    _check_chars(segments, max_chars)
    word_conf = [w["confidence"] for ln in lines for w in ln.words]
    mean = _mean(word_conf)

    warnings = [_browser_warning("Tesseract.js")]
    if not segments:
        outcome = "empty"
        warnings.append(
            ExtractionWarning("no_text_detected", "OCR did not detect any text in the image.")
        )
    elif mean is not None and mean < min_confidence:
        outcome = "partial"
        warnings.append(
            ExtractionWarning(
                "low_confidence",
                "The OCR engine reported low confidence. The text is kept but may "
                "contain misreadings.",
                {"mean_engine_confidence": round(mean, 4), "threshold": min_confidence},
            )
        )
    else:
        outcome = "ok"

    version = engine.ocr_engine_version or "unknown"
    metadata = {
        "width": width,
        "height": height,
        "ocr_engine": "tesseract.js",
        "ocr_engine_version": version,
        "ocr_language": language,
        "line_count": len(segments),
        "word_count": len(word_conf),
        "mean_engine_confidence": mean,
        "exif_orientation_applied": True,
        "text_source": "ocr",
        "processed_in": "browser",
        "size_verified_by_server": facts.image_size is not None,
        "low_confidence_lines": sum(
            1 for s in segments if (s.engine_confidence or 0) < min_confidence
        ),
    }
    return ExtractionResult(IMAGE_EXTRACTOR, version, outcome, segments, metadata, warnings)


# --- audio -----------------------------------------------------------------------------


def _check_duration(reported: float, facts: ServerFacts, limit_seconds: int) -> None:
    _finite(reported)
    if reported > limit_seconds:
        raise BrowserResultError("the recording is longer than this server accepts")
    if facts.audio_duration is not None and (
        abs(facts.audio_duration - reported) > DURATION_TOLERANCE_SECONDS
    ):
        raise BrowserResultError("the reported duration does not match the stored recording")


def _transcript(
    items: Sequence[BrowserTranscriptSegmentIn],
    duration: float,
    language: str | None,
    max_chars: int,
) -> tuple[list[SegmentDraft], bool, bool]:
    """(segments, clamped, truncated). Over the character limit the transcript is cut
    at a segment boundary and the run is reported partial, as extractors/audio.py does."""
    segments: list[SegmentDraft] = []
    clamped = truncated = False
    chars = 0
    for item in items:
        text = clean_text(item.text)
        if not text:
            continue
        start, end, was_clamped = check_span(item.start, item.end, duration)
        clamped = clamped or was_clamped
        if chars + len(text) > max_chars:
            truncated = True
            break
        chars += len(text)
        segments.append(
            SegmentDraft(
                segment_type="transcript_segment",
                text=text,
                locator=AudioLocator(start=start, end=end),
                data={"source": "machine_transcription"},
                engine_confidence=None,  # the browser engine reports no probability
                language=language,
            )
        )
    return segments, clamped, truncated


def build_audio_result(
    payload: BrowserAudioResultIn,
    engine: BrowserEngineIn,
    facts: ServerFacts,
    *,
    max_audio_seconds: int,
    max_chars: int,
) -> ExtractionResult:
    duration = payload.duration_seconds
    _check_duration(duration, facts, max_audio_seconds)
    segments, clamped, truncated = _transcript(
        payload.segments, duration, payload.language, max_chars
    )
    warnings = [_browser_warning("Whisper (Transformers.js)")]
    if clamped:
        warnings.append(
            ExtractionWarning(
                "timestamps_clamped",
                "Some segment times were slightly past the end of the recording and were "
                "set to the end.",
            )
        )
    if truncated:
        warnings.append(
            ExtractionWarning(
                "char_limit_reached",
                "The transcript was cut at the server's text limit; later speech is missing.",
            )
        )
    if not segments:
        outcome = "empty"
        warnings.append(
            ExtractionWarning("no_speech_detected", "The speech engine did not detect speech.")
        )
    else:
        outcome = "partial" if truncated else "ok"
    version = engine.speech_engine_version or "unknown"
    metadata = {
        "transcription": "machine",
        "duration_seconds": round(duration, 3),
        "duration_verified_by_server": facts.audio_duration is not None,
        "language": payload.language,
        "model": engine.speech_model,
        "device": engine.device,
        "engine": "transformers.js",
        "engine_version": version,
        "segment_count": len(segments),
        "word_timestamps": False,
        "processed_in": "browser",
    }
    return ExtractionResult(AUDIO_EXTRACTOR, version, outcome, segments, metadata, warnings)


# --- video -----------------------------------------------------------------------------


def build_video_result(
    payload: BrowserVideoResultIn,
    engine: BrowserEngineIn,
    *,
    max_video_seconds: int,
    max_frames: int,
    max_chars: int,
) -> ExtractionResult:
    duration = payload.duration_seconds
    _check_duration(duration, ServerFacts(), max_video_seconds)
    fw, fh = payload.frame_width, payload.frame_height
    if len(payload.frames) > max_frames + 1:
        raise BrowserResultError("more video frames were sampled than this server accepts")

    segments: list[SegmentDraft] = []
    frame_times: list[float] = []
    previous = -1.0
    for frame in payload.frames:
        _finite(frame.t)
        if frame.t > duration + EDGE_TOLERANCE_SECONDS:
            raise BrowserResultError("a video frame lies beyond the end of the video")
        t = round(min(frame.t, duration), 3)
        if t <= previous:
            raise BrowserResultError("video frames are not in time order")
        previous = t
        frame_times.append(t)
        lines = [ln for ln in _lines(frame.lines, fw, fh) if len(ln.text) >= MIN_VIDEO_LINE_CHARS]
        segments.append(
            SegmentDraft(
                segment_type="video_frame",
                text=" / ".join(ln.text for ln in lines) or None,
                locator=VideoLocator(t=t, frame_width=fw, frame_height=fh),
                data={
                    "sampling": frame.sampling,
                    "scene_score": None,
                    "ocr_line_count": len(lines),
                },
            )
        )
        segments.extend(
            SegmentDraft(
                segment_type="video_ocr_line",
                text=ln.text,
                locator=VideoLocator(t=t, frame_width=fw, frame_height=fh, bbox=ln.bbox),
                data={"words": ln.words, "source": "ocr_on_sampled_frame"},
                engine_confidence=ln.confidence,
                language=payload.ocr_language,
            )
            for ln in lines
        )

    # Frame text is counted first; the transcript gets what is left of the limit.
    frame_chars = sum(len(s.text or "") for s in segments)
    if frame_chars > max_chars:
        raise BrowserResultError("the result has more text than this server accepts")
    transcript, clamped, truncated = _transcript(
        payload.transcript if payload.soundtrack == "transcribed" else [],
        duration,
        payload.transcript_language,
        max_chars - frame_chars,
    )
    segments.extend(transcript)

    warnings = [
        _browser_warning("Tesseract.js and Whisper (Transformers.js)"),
        ExtractionWarning(
            "sampled_frames_only",
            "Only sampled frames were read; moments between samples were not examined.",
            {"frames": len(frame_times), "interval_seconds": payload.interval_seconds},
        ),
    ]
    if payload.soundtrack == "no_audio_track":
        warnings.append(ExtractionWarning("no_audio_track", "The video has no audio track."))
    elif payload.soundtrack == "not_transcribed":
        warnings.append(
            ExtractionWarning(
                "soundtrack_not_transcribed",
                "This browser could not decode or transcribe the soundtrack. Any speech in "
                "the video is not included.",
            )
        )
    if clamped:
        warnings.append(
            ExtractionWarning(
                "timestamps_clamped",
                "Some transcript times were slightly past the end of the video and were set "
                "to the end.",
            )
        )
    if truncated:
        warnings.append(
            ExtractionWarning(
                "char_limit_reached",
                "The transcript was cut at the server's text limit; later speech is missing.",
            )
        )
    has_text = any(s.text for s in segments)
    if not has_text:
        outcome = "empty"
    elif payload.soundtrack == "not_transcribed" or truncated:
        outcome = "partial"
    else:
        outcome = "ok"
    metadata = {
        "duration_seconds": round(duration, 3),
        "width": fw,
        "height": fh,
        "sampled_frames": len(frame_times),
        "sampling": {
            "method": "interval",
            "interval_seconds": payload.interval_seconds,
            "max_frames": max_frames,
        },
        "frame_times": frame_times,
        "frame_ocr": True,
        "ocr_engine": "tesseract.js",
        "ocr_engine_version": engine.ocr_engine_version,
        "transcript_segments": len(transcript),
        "soundtrack": {
            "status": payload.soundtrack,
            "model": engine.speech_model,
            "language": payload.transcript_language,
            "engine": "transformers.js",
            "engine_version": engine.speech_engine_version,
        },
        "processed_in": "browser",
    }
    return ExtractionResult(
        VIDEO_EXTRACTOR, VIDEO_EXTRACTOR_VERSION, outcome, segments, metadata, warnings
    )
