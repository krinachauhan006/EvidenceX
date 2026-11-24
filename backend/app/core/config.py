"""Application configuration, loaded from environment variables.

Secrets live only in the environment (or a local, untracked .env). Never hardcode
secrets and never log their values.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings sourced from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="development", alias="APP_ENV")

    # Default to a local SQLite file so the app and unit tests can run with zero
    # infrastructure. docker-compose / .env supplies a Postgres URL for real use.
    database_url: str = Field(
        default="sqlite+pysqlite:///./var/evidencex.db",
        alias="DATABASE_URL",
    )

    storage_root: str = Field(default="./var/storage", alias="STORAGE_ROOT")

    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"],
        alias="CORS_ORIGINS",
    )

    # Maximum accepted upload size in megabytes (Stage 2 evidence ingestion).
    max_upload_size_mb: int = Field(default=25, alias="MAX_UPLOAD_SIZE_MB")

    # --- Stage 3: evidence processing -------------------------------------------
    processing_max_concurrency: int = Field(default=1, ge=1, alias="PROCESSING_MAX_CONCURRENCY")
    # An item stuck in "processing" longer than this is treated as abandoned.
    processing_stale_minutes: int = Field(default=30, ge=1, alias="PROCESSING_STALE_MINUTES")
    max_pdf_pages: int = Field(default=500, ge=1, alias="MAX_PDF_PAGES")
    max_tabular_rows: int = Field(default=50_000, ge=1, alias="MAX_TABULAR_ROWS")
    max_cell_chars: int = Field(default=32_768, ge=1, alias="MAX_CELL_CHARS")
    max_extracted_chars: int = Field(default=5_000_000, ge=1, alias="MAX_EXTRACTED_CHARS")
    max_image_pixels: int = Field(default=50_000_000, ge=1, alias="MAX_IMAGE_PIXELS")

    # OCR (Tesseract). Empty TESSERACT_CMD means: look on PATH, then in the default
    # Windows install folder.
    tesseract_cmd: str = Field(default="", alias="TESSERACT_CMD")
    tesseract_langs: str = Field(default="eng", alias="TESSERACT_LANGS")
    ocr_min_confidence: float = Field(default=0.40, ge=0, le=1, alias="OCR_MIN_CONFIDENCE")
    ocr_timeout_seconds: int = Field(default=120, ge=1, alias="OCR_TIMEOUT_SECONDS")
    # Scanned PDF pages are rendered and OCR'd when Tesseract is available.
    pdf_ocr_fallback: bool = Field(default=True, alias="PDF_OCR_FALLBACK")
    # PyMuPDF is AGPL-3.0 (or commercial). Set to false to leave PDF processing off.
    pdf_extraction_enabled: bool = Field(default=True, alias="PDF_EXTRACTION_ENABLED")

    # Audio transcription (faster-whisper). Models are never downloaded implicitly.
    whisper_model_size: str = Field(default="base", alias="WHISPER_MODEL_SIZE")
    whisper_model_dir: str = Field(default="./var/models", alias="WHISPER_MODEL_DIR")
    whisper_device: str = Field(default="cpu", alias="WHISPER_DEVICE")
    whisper_compute_type: str = Field(default="int8", alias="WHISPER_COMPUTE_TYPE")
    whisper_language: str = Field(default="", alias="WHISPER_LANGUAGE")
    whisper_allow_download: bool = Field(default=False, alias="WHISPER_ALLOW_DOWNLOAD")
    whisper_vad_filter: bool = Field(default=True, alias="WHISPER_VAD_FILTER")
    # Word-level alignment. Keeps segment times inside the recording and gives the
    # engine's own per-word probability. It does not change the transcript text.
    whisper_word_timestamps: bool = Field(default=True, alias="WHISPER_WORD_TIMESTAMPS")
    # Words the engine itself rates below this probability are flagged "may be misheard".
    whisper_low_word_probability: float = Field(
        default=0.5, ge=0, le=1, alias="WHISPER_LOW_WORD_PROBABILITY"
    )
    # Optional text that biases recognition. Empty by default: in testing it fixed some
    # words but also changed meaning elsewhere, so every use is flagged on the result.
    whisper_initial_prompt: str = Field(default="", alias="WHISPER_INITIAL_PROMPT")
    # Longest recording that is transcribed. Checked while decoding, before the model
    # is loaded. 20 minutes decodes to about 77 MB of samples.
    max_audio_seconds: int = Field(default=1200, ge=1, alias="MAX_AUDIO_SECONDS")
    # Wall-clock limit for one audio item (decode + model load + transcription).
    # Checked between transcript windows, so it can overrun by one window (~30 s audio).
    audio_timeout_seconds: int = Field(default=1800, ge=1, alias="AUDIO_TIMEOUT_SECONDS")

    # ZIP package limits for .xlsx (applied at upload and again before parsing).
    max_zip_entries: int = Field(default=2_000, ge=1, alias="MAX_ZIP_ENTRIES")
    max_zip_uncompressed_mb: int = Field(default=100, ge=1, alias="MAX_ZIP_UNCOMPRESSED_MB")
    max_zip_entry_mb: int = Field(default=50, ge=1, alias="MAX_ZIP_ENTRY_MB")
    max_shared_strings_mb: int = Field(default=20, ge=1, alias="MAX_SHARED_STRINGS_MB")
    max_zip_compression_ratio: int = Field(default=100, ge=1, alias="MAX_ZIP_COMPRESSION_RATIO")

    # --- Phase 1: analysis (claims, entities, potential contradictions) ---------
    # "rule_based" (default, deterministic, offline) or "gemini" (needs GEMINI_API_KEY
    # and network). Gemini is never used unless both are set.
    claim_extractor: str = Field(default="rule_based", alias="CLAIM_EXTRACTOR")
    gemini_model: str = Field(default="gemini-2.0-flash", alias="GEMINI_MODEL")
    gemini_timeout_seconds: int = Field(default=60, ge=1, alias="GEMINI_TIMEOUT_SECONDS")
    # A case analysis still "running" after this long is treated as abandoned.
    analysis_stale_minutes: int = Field(default=30, ge=1, alias="ANALYSIS_STALE_MINUTES")

    # Secret — never logged, never returned in responses.
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, value: object) -> object:
        """Allow CORS_ORIGINS as a comma-separated string in the environment."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
