"""Application configuration, loaded from environment variables.

Secrets live only in the environment (or a local, untracked .env). Never hardcode
secrets and never log their values.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# A MIME type as stored on evidence rows: "type/subtype", lower case.
_MIME_RE = re.compile(r"[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*")


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
    # --- Postgres connection pool (ignored for SQLite) ------------------------------
    # Connections kept open per process. Serverless instances each hold their own pool,
    # so keep this small; the managed database's connection limit is shared by all.
    database_pool_size: int = Field(default=2, ge=1, le=50, alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=3, ge=0, le=50, alias="DATABASE_MAX_OVERFLOW")
    # Seconds after which a pooled connection is replaced (managed databases and
    # poolers close idle connections).
    database_pool_recycle_seconds: int = Field(
        default=300, ge=30, alias="DATABASE_POOL_RECYCLE_SECONDS"
    )
    # True when DATABASE_URL points at a TRANSACTION-mode pooler (PgBouncer-style, e.g.
    # Supabase port 6543). Then no client-side pool is kept (the pooler is the pool)
    # and psycopg prepared statements are disabled, which such poolers do not support.
    database_transaction_pooler: bool = Field(default=False, alias="DATABASE_TRANSACTION_POOLER")

    # Set to "1" by Vercel in every build and function (read-only here). Enables the
    # serverless configuration checks in app/core/deploy_checks.py.
    vercel: bool = Field(default=False, alias="VERCEL")

    storage_root: str = Field(default="./var/storage", alias="STORAGE_ROOT")

    # Evidence blob storage: "local" (default, files under STORAGE_ROOT) or "s3" (an
    # S3-compatible bucket such as Supabase Storage; see app/storage/s3_store.py).
    storage_backend: Literal["local", "s3"] = Field(default="local", alias="STORAGE_BACKEND")
    # Used only when STORAGE_BACKEND=s3. Empty endpoint = AWS S3 itself.
    s3_endpoint_url: str = Field(default="", alias="S3_ENDPOINT_URL")
    s3_bucket: str = Field(default="", alias="S3_BUCKET")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    s3_access_key_id: str = Field(default="", alias="S3_ACCESS_KEY_ID")
    # Secret — never logged, never returned in responses (SecretStr hides it in repr).
    s3_secret_access_key: SecretStr = Field(default=SecretStr(""), alias="S3_SECRET_ACCESS_KEY")

    # NoDecode: the environment value is a comma-separated string (or a JSON list), and
    # is split by ``_split_cors`` below. Without it pydantic-settings tries json.loads on
    # "http://a,http://b" and refuses to start.
    # Both loopback names by default, so the local frontend works whether it is opened
    # as localhost or 127.0.0.1 (the browser treats them as different sites).
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"],
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
    # "gemini-2.0-flash" is restricted to existing customers since 2026-03; 3.8 Flash is
    # listed as Stable on the Gemini models page (checked 2026-11). Configurable.
    gemini_model: str = Field(default="gemini-3.8-flash", alias="GEMINI_MODEL")
    gemini_timeout_seconds: int = Field(default=60, ge=1, alias="GEMINI_TIMEOUT_SECONDS")
    # A case analysis still "running" after this long is treated as abandoned.
    analysis_stale_minutes: int = Field(default=30, ge=1, alias="ANALYSIS_STALE_MINUTES")

    # Secret — never logged, never returned in responses.
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")

    # --- Phase 2: authentication -------------------------------------------------
    session_days: int = Field(default=7, ge=1, le=90, alias="SESSION_DAYS")
    session_cookie_name: str = Field(default="evx_session", alias="SESSION_COOKIE_NAME")
    # Must be true in production (HTTPS). False only for local http://localhost.
    cookie_secure: bool = Field(default=False, alias="COOKIE_SECURE")
    registration_open: bool = Field(default=True, alias="REGISTRATION_OPEN")
    login_max_failures: int = Field(default=8, ge=1, alias="LOGIN_MAX_FAILURES")
    login_lockout_minutes: int = Field(default=15, ge=1, alias="LOGIN_LOCKOUT_MINUTES")
    # Cases created before authentication existed (Phase 1) have no members. They are
    # given to exactly ONE operator-designated account: the account registering with
    # this e-mail address becomes their owner. When empty, nobody receives them
    # automatically; the operator runs ``python -m app.cli claim-legacy-cases EMAIL``.
    # They are never visible to an arbitrary (e.g. merely the first) account.
    legacy_cases_owner_email: str = Field(default="", alias="LEGACY_CASES_OWNER_EMAIL")

    # --- Phase 2: video ------------------------------------------------------------
    max_video_seconds: int = Field(default=1800, ge=1, alias="MAX_VIDEO_SECONDS")
    max_video_upload_mb: int = Field(default=200, ge=1, alias="MAX_VIDEO_UPLOAD_MB")
    video_frame_interval_seconds: float = Field(
        default=10.0, gt=0, alias="VIDEO_FRAME_INTERVAL_SECONDS"
    )
    video_max_frames: int = Field(default=60, ge=1, le=500, alias="VIDEO_MAX_FRAMES")
    # Mean absolute grey-level difference (0-255) that counts as a scene change.
    video_scene_threshold: float = Field(default=28.0, gt=0, alias="VIDEO_SCENE_THRESHOLD")
    video_ocr_frames: bool = Field(default=True, alias="VIDEO_OCR_FRAMES")
    video_transcribe_audio: bool = Field(default=True, alias="VIDEO_TRANSCRIBE_AUDIO")

    # --- Phase 2: OCR preprocessing and isolation -------------------------------------
    ocr_preprocess: bool = Field(default=True, alias="OCR_PREPROCESS")
    # inline | subprocess (hard timeout + crash isolation for risky formats)
    processing_isolation: str = Field(default="subprocess", alias="PROCESSING_ISOLATION")
    processing_item_timeout_seconds: int = Field(
        default=2400, ge=10, alias="PROCESSING_ITEM_TIMEOUT_SECONDS"
    )

    # --- External processing worker -----------------------------------------------
    # Comma-separated MIME types that THIS server must not process because a separate
    # worker does (``python -m app.cli worker``, e.g. on a computer with Tesseract, the
    # speech model and PyAV). Set on a serverless deployment that lacks those engines.
    # Such items are never claimed here: they stay "pending" and are reported with the
    # skip reason "external_worker". Empty (default) = this server processes everything.
    external_worker_mimes_raw: str = Field(default="", alias="EXTERNAL_WORKER_MIMES")

    @field_validator("external_worker_mimes_raw", mode="before")
    @classmethod
    def _normalise_worker_mimes(cls, value: object) -> object:
        """Lower-case, de-duplicated, comma-separated ``type/subtype`` list. A malformed
        entry is refused at start-up rather than silently ignored (a typo would let the
        server claim and fail items the worker should process)."""
        if value is None:
            return ""
        if not isinstance(value, str):
            return value
        seen: list[str] = []
        for part in value.replace(";", ",").split(","):
            mime = part.strip().lower()
            if not mime:
                continue
            if not _MIME_RE.fullmatch(mime):
                raise ValueError(
                    f"EXTERNAL_WORKER_MIMES contains an invalid MIME type {mime!r}; "
                    "use comma-separated values such as image/png,audio/wav"
                )
            if mime not in seen:
                seen.append(mime)
        return ",".join(seen)

    @property
    def external_worker_mimes(self) -> frozenset[str]:
        """MIME types handled by the external worker (empty = none)."""
        return frozenset(m for m in self.external_worker_mimes_raw.split(",") if m)

    @field_validator("database_url", mode="before")
    @classmethod
    def _psycopg_driver(cls, value: object) -> object:
        """Managed providers hand out ``postgres://`` or ``postgresql://`` URLs. Without
        a driver name SQLAlchemy would look for psycopg2, which is not installed; use
        psycopg (v3), which is. URLs that already name a driver are left unchanged."""
        if isinstance(value, str):
            text = value.strip()
            for prefix in ("postgres://", "postgresql://"):
                if text.startswith(prefix):
                    return "postgresql+psycopg://" + text[len(prefix) :]
            return text
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, value: object) -> object:
        """Allow CORS_ORIGINS as a comma-separated string or a JSON list."""
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                import json

                return json.loads(text)
            return [origin.strip().rstrip("/") for origin in text.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
