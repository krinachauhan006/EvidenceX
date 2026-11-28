"""Request and response schemas for in-browser processing.

The browser runs the OCR or speech engine on a file it downloaded from this server and
submits what the engine read. Everything here is UNTRUSTED input: every string is
length-capped, every list size-capped, unknown fields are refused, and the service
re-checks every position against the file (``browser_results.py``) before anything is
saved. Text is evidence content (data), never instructions.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.processing.locators import BBox

# Engine and model identifiers are shown in the run history. Plain tokens only.
_VERSION = r"^[A-Za-z0-9._+-]{1,24}$"
_MODEL = r"^[A-Za-z0-9._/-]{1,64}$"
# Tesseract codes ("eng", "eng+deu") or Whisper language names/codes ("en", "english").
_LANG = r"^[a-z_+-]{2,32}$"

MAX_OCR_LINES = 20_000
MAX_WORDS_PER_LINE = 1_000
MAX_TRANSCRIPT_SEGMENTS = 50_000
MAX_VIDEO_FRAMES = 501  # VIDEO_MAX_FRAMES is capped at 500, plus the first frame
MAX_LINES_PER_FRAME = 2_000


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BrowserWordIn(_In):
    text: str = Field(min_length=1, max_length=200)
    bbox: BBox
    confidence: float = Field(ge=0, le=1)


class BrowserOcrLineIn(_In):
    text: str = Field(min_length=1, max_length=4_000)
    bbox: BBox
    # Recomputed on the server from the words when they are present.
    confidence: float | None = Field(default=None, ge=0, le=1)
    words: list[BrowserWordIn] = Field(default_factory=list, max_length=MAX_WORDS_PER_LINE)


class BrowserImageResultIn(_In):
    kind: Literal["image"]
    # Pixel size of the image the engine read, after the EXIF orientation was applied.
    width: int = Field(ge=1, le=100_000)
    height: int = Field(ge=1, le=100_000)
    language: str = Field(pattern=_LANG)
    lines: list[BrowserOcrLineIn] = Field(max_length=MAX_OCR_LINES)


class BrowserTranscriptSegmentIn(_In):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str = Field(min_length=1, max_length=20_000)


class BrowserAudioResultIn(_In):
    kind: Literal["audio"]
    duration_seconds: float = Field(gt=0, le=86_400)
    language: str | None = Field(default=None, pattern=_LANG)
    segments: list[BrowserTranscriptSegmentIn] = Field(max_length=MAX_TRANSCRIPT_SEGMENTS)


class BrowserVideoFrameIn(_In):
    t: float = Field(ge=0)
    sampling: Literal["first_frame", "interval"]
    lines: list[BrowserOcrLineIn] = Field(default_factory=list, max_length=MAX_LINES_PER_FRAME)


class BrowserVideoResultIn(_In):
    kind: Literal["video"]
    duration_seconds: float = Field(gt=0, le=86_400)
    frame_width: int = Field(ge=1, le=8_192)
    frame_height: int = Field(ge=1, le=8_192)
    interval_seconds: float = Field(gt=0, le=3_600)
    ocr_language: str = Field(pattern=_LANG)
    frames: list[BrowserVideoFrameIn] = Field(max_length=MAX_VIDEO_FRAMES)
    # "not_transcribed": the soundtrack exists (or may exist) but this browser could not
    # decode or transcribe it. Never presented as "no speech".
    soundtrack: Literal["transcribed", "no_audio_track", "not_transcribed"]
    transcript_language: str | None = Field(default=None, pattern=_LANG)
    transcript: list[BrowserTranscriptSegmentIn] = Field(
        default_factory=list, max_length=MAX_TRANSCRIPT_SEGMENTS
    )


BrowserResult = Annotated[
    BrowserImageResultIn | BrowserAudioResultIn | BrowserVideoResultIn,
    Field(discriminator="kind"),
]


class BrowserEngineIn(_In):
    ocr_engine_version: str | None = Field(default=None, pattern=_VERSION)
    speech_engine_version: str | None = Field(default=None, pattern=_VERSION)
    speech_model: str | None = Field(default=None, pattern=_MODEL)
    device: Literal["wasm", "webgpu"] | None = None


class BrowserResultIn(_In):
    run_number: int = Field(ge=1)
    # SHA-256 of the bytes the browser processed; must equal the stored file's.
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration_ms: int = Field(ge=0, le=86_400_000)
    engine: BrowserEngineIn
    result: BrowserResult


class BrowserClaimIn(_In):
    # Re-process an item that is already completed (adds a new run; earlier runs kept).
    force: bool = False


class BrowserHeartbeatIn(_In):
    run_number: int = Field(ge=1)


# What the browser may report as the reason it stopped. The stored message is chosen by
# the server (``browser_service.FAILURE_MESSAGES``); no client text is stored.
BrowserFailureCode = Literal[
    "interrupted", "browser_engine_failed", "browser_decode_failed", "browser_out_of_memory"
]


class BrowserFailureIn(_In):
    run_number: int = Field(ge=1)
    code: BrowserFailureCode


class BrowserLimitsOut(BaseModel):
    max_extracted_chars: int
    max_audio_seconds: int
    max_video_seconds: int
    video_max_frames: int
    video_frame_interval_seconds: float


class BrowserClaimOut(BaseModel):
    """The browser now owns run ``run_number`` of this item until it submits, reports a
    failure, or stops sending heartbeats for ``stale_seconds``."""

    evidence_id: uuid.UUID
    run_number: int
    kind: Literal["image", "audio", "video"]
    mime_type: str
    sha256: str
    byte_size: int
    heartbeat_seconds: int
    stale_seconds: int
    ocr_language: str
    limits: BrowserLimitsOut
