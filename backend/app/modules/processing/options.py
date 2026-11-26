"""Engine options handed to extractors (OCR, speech). Built from settings only."""

from __future__ import annotations

from typing import Any

from app.core.config import Settings


def engine_options(settings: Settings) -> dict[str, Any]:
    return {
        "tesseract_cmd": settings.tesseract_cmd,
        "tesseract_langs": settings.tesseract_langs,
        "ocr_min_confidence": settings.ocr_min_confidence,
        "ocr_timeout_seconds": settings.ocr_timeout_seconds,
        "pdf_ocr_fallback": settings.pdf_ocr_fallback,
        "whisper_model_size": settings.whisper_model_size,
        "whisper_model_dir": settings.whisper_model_dir,
        "whisper_device": settings.whisper_device,
        "whisper_compute_type": settings.whisper_compute_type,
        "whisper_language": settings.whisper_language,
        "whisper_allow_download": settings.whisper_allow_download,
        "whisper_vad_filter": settings.whisper_vad_filter,
        "whisper_word_timestamps": settings.whisper_word_timestamps,
        "whisper_low_word_probability": settings.whisper_low_word_probability,
        "whisper_initial_prompt": settings.whisper_initial_prompt,
        "max_audio_seconds": settings.max_audio_seconds,
        "audio_timeout_seconds": settings.audio_timeout_seconds,
        # Phase 2
        "max_video_seconds": settings.max_video_seconds,
        "video_frame_interval_seconds": settings.video_frame_interval_seconds,
        "video_max_frames": settings.video_max_frames,
        "video_scene_threshold": settings.video_scene_threshold,
        "video_ocr_frames": settings.video_ocr_frames,
        "video_transcribe_audio": settings.video_transcribe_audio,
        "ocr_preprocess": settings.ocr_preprocess,
    }
