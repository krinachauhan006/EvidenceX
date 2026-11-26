"""Video extractor (PyAV / FFmpeg): metadata, sampled frames, frame OCR, soundtrack.

Strategy (documented limits):
- Metadata: duration, frame rate, size, codecs, whether there is an audio track.
- Frames are SAMPLED, never all decoded: a probe frame every ``probe_step`` seconds
  (at least 1 s, more for long videos) is compared with the previous probe; a frame is
  kept at every ``VIDEO_FRAME_INTERVAL_SECONDS`` and wherever the mean grey-level
  difference exceeds ``VIDEO_SCENE_THRESHOLD`` (a scene change), up to
  ``VIDEO_MAX_FRAMES``. Moments between samples are NOT examined.
- Each kept frame becomes a ``video_frame`` segment at its exact time; text found by
  OCR on it becomes ``video_ocr_line`` segments with the frame time and pixel box.
- The soundtrack is transcribed by the existing audio pipeline; its segments keep
  their start/end times, which are the same media timeline as the frames.
- Frame images are not stored; they are re-decoded on demand at the cited time.
- No face recognition and no authenticity analysis are performed.
"""

from __future__ import annotations

import io
import time
from collections.abc import Iterator
from typing import Any

from app.modules.processing.errors import (
    CorruptFileError,
    DependencyMissingError,
    ExtractionError,
    ExtractionTimeoutError,
    LimitExceededError,
)
from app.modules.processing.extractors.base import (
    ExtractionInput,
    ExtractionResult,
    ExtractionWarning,
    SegmentDraft,
)
from app.modules.processing.extractors.ocr_engine import OcrEngine, TesseractEngine
from app.modules.processing.locators import VideoLocator

THUMB = (64, 36)


def _av() -> Any:
    try:
        import av
    except ImportError as exc:
        raise DependencyMissingError("PyAV is not installed (pip install av).") from exc
    return av


def probe(data: bytes) -> dict[str, Any]:
    """Container and stream metadata. Raises CorruptFileError for undecodable input."""
    av = _av()
    try:
        with av.open(io.BytesIO(data), mode="r") as c:
            if not c.streams.video:
                raise CorruptFileError("The file has no video stream.")
            vs = c.streams.video[0]
            duration = None
            if vs.duration is not None and vs.time_base is not None:
                duration = float(vs.duration * vs.time_base)
            elif c.duration is not None:
                duration = c.duration / 1_000_000
            rate = vs.average_rate or vs.guessed_rate
            audio = c.streams.audio[0] if c.streams.audio else None
            return {
                "duration_seconds": round(duration, 3) if duration else None,
                "frame_rate": round(float(rate), 3) if rate else None,
                "width": vs.codec_context.width,
                "height": vs.codec_context.height,
                "video_codec": vs.codec_context.name,
                "container": c.format.name,
                "has_audio": audio is not None,
                "audio_codec": audio.codec_context.name if audio else None,
                "frame_count_reported": vs.frames or None,
            }
    except ExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 - any demux/decode error means a bad file
        raise CorruptFileError("The video could not be read.") from exc


def frame_at(data: bytes, t: float, max_width: int = 960) -> Any:
    """The first decodable frame at or after ``t`` seconds, as a Pillow image."""
    av = _av()
    with av.open(io.BytesIO(data), mode="r") as c:
        vs = c.streams.video[0]
        vs.thread_type = "AUTO"
        tb = vs.time_base
        if t > 0 and tb:
            c.seek(int(t / tb), stream=vs, backward=True, any_frame=False)
        last = None
        for frame in c.decode(vs):
            last = frame
            ft = float(frame.pts * tb) if frame.pts is not None and tb else 0.0
            if ft + 1e-3 >= t:
                break
        if last is None:
            raise CorruptFileError("No frame could be decoded at this time.")
        img = last.to_image()
    if img.width > max_width:
        img = img.resize((max_width, round(img.height * max_width / img.width)))
    return img


def _probes(data: bytes, times: list[float]) -> Iterator[tuple[float, Any]]:
    """Decode one frame per probe time with seeking (never every frame)."""
    av = _av()
    with av.open(io.BytesIO(data), mode="r") as c:
        vs = c.streams.video[0]
        tb = vs.time_base
        for t in times:
            if tb:
                c.seek(int(t / tb), stream=vs, backward=True, any_frame=False)
            got = None
            for frame in c.decode(vs):
                ft = float(frame.pts * tb) if frame.pts is not None and tb else t
                got = (ft, frame)
                if ft + 1e-3 >= t:
                    break
            if got is not None:
                yield max(0.0, got[0]), got[1].to_image()


def _grey(img: Any) -> list[int]:
    return list(img.convert("L").resize(THUMB).tobytes())  # one byte per pixel in "L"


def _diff(a: list[int], b: list[int]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b, strict=False)) / max(1, len(a))


def plan_probes(duration: float, interval: float) -> tuple[list[float], float]:
    step = max(1.0, duration / 600.0, min(interval, 2.0))
    times, t = [], 0.0
    while t < duration:
        times.append(round(t, 3))
        t += step
    return times or [0.0], step


class VideoExtractor:
    name = "video"
    version = "1"

    def __init__(self, ocr: OcrEngine | None = None, audio: Any = None) -> None:
        self._ocr: OcrEngine = ocr or TesseractEngine()
        self._audio = audio  # an AudioExtractor; created lazily when needed

    def extract(self, inp: ExtractionInput) -> ExtractionResult:
        opts = inp.options
        started = time.monotonic()
        timeout = float(opts.get("audio_timeout_seconds") or 1800)
        meta = probe(inp.data)
        duration = meta["duration_seconds"] or 0.0
        if duration > float(opts.get("max_video_seconds") or 1800):
            raise LimitExceededError(
                f"The video is longer than {opts.get('max_video_seconds')} seconds."
            )
        interval = float(opts.get("video_frame_interval_seconds") or 10.0)
        threshold = float(opts.get("video_scene_threshold") or 28.0)
        max_frames = int(opts.get("video_max_frames") or 60)
        warnings: list[ExtractionWarning] = []
        segments: list[SegmentDraft] = []

        times, step = plan_probes(duration, interval)
        kept: list[tuple[float, Any, str, float | None]] = []
        prev, last_kept_t = None, -1e9
        for t, img in _probes(inp.data, times):
            if time.monotonic() - started > timeout:
                raise ExtractionTimeoutError("Video processing took too long and was stopped.")
            g = _grey(img)
            score = _diff(prev, g) if prev is not None else None
            prev = g
            reason = None
            if not kept:
                reason = "first_frame"
            elif score is not None and score >= threshold:
                reason = "scene_change"
            elif t - last_kept_t >= interval - 1e-6:
                reason = "interval"
            if reason:
                kept.append((t, img, reason, score))
                last_kept_t = t
                if len(kept) >= max_frames:
                    warnings.append(
                        ExtractionWarning(
                            "frame_limit_reached",
                            f"Frame sampling stopped at {max_frames} frames; later parts of the "
                            "video were not sampled.",
                            {"limit": max_frames, "at_seconds": t},
                        )
                    )
                    break

        ocr_on = bool(opts.get("video_ocr_frames", True))
        ocr_available = True
        langs = str(opts.get("tesseract_langs") or "eng")
        for t, img, reason, score in kept:
            w, h = img.size
            lines: list[Any] = []
            if ocr_on and ocr_available:
                try:
                    from app.modules.processing.extractors.ocr_engine import (
                        group_words_into_lines,
                    )

                    raw = self._ocr.recognize(img.convert("RGB"), opts)
                    lines = [
                        ln for ln in group_words_into_lines(raw, w, h) if len(ln.text.strip()) >= 2
                    ]
                except DependencyMissingError as exc:
                    ocr_available = False
                    warnings.append(
                        ExtractionWarning(
                            "ocr_unavailable", f"Frame text was not read: {exc.message}"
                        )
                    )
            segments.append(
                SegmentDraft(
                    segment_type="video_frame",
                    text=" / ".join(ln.text for ln in lines) or None,
                    locator=VideoLocator(t=round(t, 3), frame_width=w, frame_height=h),
                    data={
                        "sampling": reason,
                        "scene_score": round(score, 2) if score else None,
                        "ocr_line_count": len(lines),
                    },
                )
            )
            for ln in lines:
                segments.append(
                    SegmentDraft(
                        segment_type="video_ocr_line",
                        text=ln.text,
                        locator=VideoLocator(
                            t=round(t, 3), frame_width=w, frame_height=h, bbox=ln.bbox
                        ),
                        data={"words": ln.words, "source": "ocr_on_sampled_frame"},
                        engine_confidence=ln.confidence,
                        language=langs,
                    )
                )

        transcript_count = 0
        audio_meta: dict[str, Any] = {}
        if meta["has_audio"] and opts.get("video_transcribe_audio", True):
            try:
                from app.modules.processing.extractors.audio import AudioExtractor

                audio = self._audio or AudioExtractor()
                result = audio.extract(inp)  # decodes the soundtrack from the container
                for s in result.segments:
                    segments.append(s)  # transcript_segment, start/end on the media timeline
                transcript_count = len(result.segments)
                warnings.extend(result.warnings)
                audio_meta = {
                    k: result.metadata.get(k)
                    for k in ("model", "language", "engine", "duration_seconds")
                }
            except ExtractionError as exc:
                warnings.append(
                    ExtractionWarning(
                        "soundtrack_not_transcribed",
                        f"The soundtrack was not transcribed: {exc.message}",
                        {"error_code": exc.code},
                    )
                )
        elif not meta["has_audio"]:
            warnings.append(ExtractionWarning("no_audio_track", "The video has no audio track."))

        warnings.append(
            ExtractionWarning(
                "sampled_frames_only",
                f"{len(kept)} frame(s) were sampled from {duration:.0f} s of video (probe every "
                f"{step:.1f} s, keep every {interval:.0f} s and at scene changes). Moments "
                "between samples were not examined.",
                {"frames": len(kept), "probe_step_seconds": step, "interval_seconds": interval},
            )
        )
        text_segments = [s for s in segments if s.text]
        outcome = "ok" if text_segments else "empty"
        if (
            any(
                w.code in ("soundtrack_not_transcribed", "ocr_unavailable", "frame_limit_reached")
                for w in warnings
            )
            and text_segments
        ):
            outcome = "partial"
        metadata = {
            **meta,
            "sampled_frames": len(kept),
            "sampling": {
                "probe_step_seconds": step,
                "interval_seconds": interval,
                "scene_threshold": threshold,
                "max_frames": max_frames,
            },
            "frame_times": [round(k[0], 3) for k in kept],
            "frame_ocr": ocr_on and ocr_available,
            "transcript_segments": transcript_count,
            "soundtrack": audio_meta,
            "processing_seconds": round(time.monotonic() - started, 2),
        }
        return ExtractionResult(self.name, self.version, outcome, segments, metadata, warnings)
