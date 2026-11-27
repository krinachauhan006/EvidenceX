"""Start-up configuration checks for the deployment environment.

Run once when the application starts (``create_app`` lifespan), before any request is
served. Each check reports the setting NAME and what to do, never a value, so secrets
cannot end up in logs or error output.

- Any environment: ``STORAGE_BACKEND=s3`` needs its bucket and credentials, and the S3
  client is constructed here (constructing it makes no network request).
- ``APP_ENV=production``: the session cookie must be marked Secure (HTTPS).
- On Vercel (``VERCEL=1``, set by the platform): state must live outside the function,
  because its filesystem is temporary and not shared between instances, and extraction
  must run inline (no worker subprocesses in a serverless function).

Upload limits above Vercel's request-body limit are reported as warnings, not errors:
the API still works, but Vercel refuses larger requests before they reach it.
"""

from __future__ import annotations

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Vercel Functions accept request bodies up to 4.5 MB (vercel.com/docs/functions/limitations).
VERCEL_REQUEST_BODY_MB = 4.5


class ConfigurationError(RuntimeError):
    """The application refused to start because its configuration is unsafe or incomplete."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__(
            "EvidenceX configuration is not valid for this environment:\n- " + "\n- ".join(problems)
        )


def configuration_problems(settings: Settings) -> list[str]:
    """Every blocking configuration problem, described by setting name only."""
    problems: list[str] = []

    if settings.storage_backend == "s3":
        from app.storage.factory import build_storage, missing_s3_settings

        missing = missing_s3_settings(settings)
        if missing:
            problems.append("STORAGE_BACKEND=s3 requires " + ", ".join(missing) + " to be set.")
        else:
            try:
                build_storage(settings)  # constructs the client; no network request
            except Exception as exc:  # noqa: BLE001 - reported by type only
                problems.append(
                    f"The S3 storage client could not be created ({type(exc).__name__}). "
                    "Check S3_ENDPOINT_URL and S3_REGION."
                )

    if settings.app_env == "production" and not settings.cookie_secure:
        problems.append(
            "COOKIE_SECURE must be true when APP_ENV=production (the site is served over "
            "HTTPS and the session cookie must not be sent over plain HTTP)."
        )

    if settings.vercel:
        if settings.database_url.startswith("sqlite"):
            problems.append(
                "DATABASE_URL must point at PostgreSQL on Vercel. A SQLite file would live "
                "on the function's temporary disk and be lost and not shared."
            )
        if settings.storage_backend == "local":
            problems.append(
                "STORAGE_BACKEND must be s3 on Vercel. Local storage would keep evidence on "
                "the function's temporary disk, where it is lost."
            )
        if settings.processing_isolation != "inline":
            problems.append(
                "PROCESSING_ISOLATION must be inline on Vercel. Extraction worker "
                "subprocesses are not supported in serverless functions."
            )
    return problems


def configuration_warnings(settings: Settings) -> list[str]:
    warnings: list[str] = []
    if settings.vercel:
        for name, value in (
            ("MAX_UPLOAD_SIZE_MB", settings.max_upload_size_mb),
            ("MAX_VIDEO_UPLOAD_MB", settings.max_video_upload_mb),
        ):
            if value > VERCEL_REQUEST_BODY_MB:
                warnings.append(
                    f"{name}={value} is above Vercel's {VERCEL_REQUEST_BODY_MB} MB request "
                    "limit; Vercel refuses larger uploads (HTTP 413) before they reach the "
                    "API. Set it to 4 to report the limit clearly."
                )
    return warnings


def check_deployment_config(settings: Settings) -> None:
    """Refuse to start on a blocking problem; log warnings."""
    for warning in configuration_warnings(settings):
        logger.warning("configuration: %s", warning)
    problems = configuration_problems(settings)
    if problems:
        raise ConfigurationError(problems)
