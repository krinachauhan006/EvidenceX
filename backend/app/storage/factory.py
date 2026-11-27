"""Choose the evidence storage backend from settings.

``STORAGE_BACKEND=local`` (the default) keeps blobs under ``STORAGE_ROOT`` on the local
disk, exactly as before. ``STORAGE_BACKEND=s3`` uses an S3-compatible bucket (for
example Supabase Storage); see ``s3_store.py``.
"""

from __future__ import annotations

import hashlib
import threading

from app.core.config import Settings
from app.storage.local_store import LocalStorage, Storage

# One S3Storage (and one thread-safe boto3 client) per configuration, so services built
# per request do not create a new client each time. The cache key is a SHA-256
# fingerprint of the configuration: the plaintext secret is never used as a key.
_S3_CACHE: dict[str, Storage] = {}
_S3_LOCK = threading.Lock()


def _fingerprint(settings: Settings) -> str:
    h = hashlib.sha256()
    for part in (
        settings.s3_bucket,
        settings.s3_endpoint_url,
        settings.s3_region,
        settings.s3_access_key_id,
        settings.s3_secret_access_key.get_secret_value(),
    ):
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def missing_s3_settings(settings: Settings) -> list[str]:
    """Names (never values) of required S3 settings that are empty."""
    required = {
        "S3_BUCKET": settings.s3_bucket,
        "S3_ACCESS_KEY_ID": settings.s3_access_key_id,
        "S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key.get_secret_value(),
    }
    return [name for name, value in required.items() if not value.strip()]


def _build_s3(settings: Settings) -> Storage:
    from app.storage.s3_store import S3Storage

    return S3Storage(
        bucket=settings.s3_bucket,
        endpoint_url=settings.s3_endpoint_url,
        region=settings.s3_region,
        access_key_id=settings.s3_access_key_id,
        secret_access_key=settings.s3_secret_access_key.get_secret_value(),
    )


def build_storage(settings: Settings) -> Storage:
    """The storage backend named by ``settings.storage_backend``."""
    if settings.storage_backend != "s3":
        return LocalStorage(settings.storage_root)
    key = _fingerprint(settings)
    storage = _S3_CACHE.get(key)
    if storage is None:
        with _S3_LOCK:
            storage = _S3_CACHE.get(key)
            if storage is None:
                storage = _build_s3(settings)
                _S3_CACHE[key] = storage
    return storage


def clear_storage_cache() -> None:
    """Forget cached S3 clients (tests, or after credentials are rotated)."""
    with _S3_LOCK:
        _S3_CACHE.clear()
