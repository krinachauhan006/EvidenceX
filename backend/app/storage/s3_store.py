"""Content-addressed evidence storage in an S3-compatible bucket.

Intended for Supabase Storage (its S3 endpoint), and also works with AWS S3,
Cloudflare R2 or MinIO. Same contract and security invariants as ``LocalStorage``:

- Object keys come ONLY from the validated SHA-256 (``aa/bb/<hash>``), never from a
  user-supplied filename, so a key cannot traverse or collide.
- Content is never executed or interpreted; it is stored as opaque bytes.
- A missing object behaves exactly like a missing local file: ``exists`` returns
  False, ``open`` raises ``FileNotFoundError``, ``delete`` returns False.
- Any other storage failure raises ``StorageUnavailableError`` (HTTP 503, generic
  message). Credentials, endpoint details and raw provider messages are never put
  into exceptions, logs or responses; logs carry the operation and the provider's
  error code only.

``boto3`` is imported lazily, so local development and Docker deployments that use
``LocalStorage`` never need it at runtime.
"""

from __future__ import annotations

import hashlib
import io
import tempfile
from typing import Any, BinaryIO

from app.core.exceptions import EvidenceXError
from app.core.logging import get_logger
from app.storage.local_store import CHUNK_SIZE, LocalStorage

logger = get_logger(__name__)

# Uploads up to this size are spooled in memory; larger ones spill to a temp file.
SPOOL_MEMORY_BYTES = 8 * 1024 * 1024
# Provider error codes that mean "no such object" (S3, S3-compatible services).
_MISSING_CODES = frozenset({"404", "NoSuchKey", "NotFound", "NoSuchObject"})


class StorageUnavailableError(EvidenceXError, OSError):
    """The object store could not complete an operation.

    It is an ``EvidenceXError`` so an API request that needs the file answers 503 with
    a generic message, and an ``OSError`` so existing best-effort cleanup paths (which
    catch ``OSError``) keep treating a failed delete as non-fatal."""

    status_code = 503
    message = "Evidence storage is temporarily unavailable. Please try again."


class StorageConfigError(ValueError):
    """The S3 storage settings are incomplete. Raised at construction, never per request."""


def _error_code(exc: BaseException) -> str:
    """The provider's error code (e.g. ``NoSuchKey``, ``403``), or the exception type."""
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = (response.get("Error") or {}).get("Code")
        if code:
            return str(code)
        status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
        if status:
            return str(status)
    return type(exc).__name__


def _is_missing(exc: BaseException) -> bool:
    return _error_code(exc) in _MISSING_CODES


def _unavailable(operation: str, exc: BaseException) -> StorageUnavailableError:
    # Only the operation and the provider error code are logged: never the
    # exception text (it can include request details) and never credentials.
    logger.warning("object storage %s failed (%s)", operation, _error_code(exc))
    return StorageUnavailableError()


class _ObjectStream(io.RawIOBase):
    """A read-only, closable stream over an S3 object body.

    Supports ``read(n)``, ``read()``, use as a context manager and repeated
    ``close()`` calls, which is what the download route, the PDF/frame previews and
    the processing runner rely on. Read failures become ``StorageUnavailableError``.
    """

    def __init__(self, body: Any) -> None:
        super().__init__()
        self._body = body

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        if self.closed:
            raise ValueError("I/O operation on closed stream")
        try:
            data = self._body.read() if size is None or size < 0 else self._body.read(size)
        except Exception as exc:  # noqa: BLE001 - mapped to a generic storage error
            raise _unavailable("read", exc) from None
        return data or b""

    def readinto(self, buffer: Any) -> int:
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)

    def close(self) -> None:
        if not self.closed:
            try:
                self._body.close()
            except Exception:  # noqa: BLE001 - releasing the connection is best effort
                logger.debug("closing an object stream failed")
        super().close()


def _build_client(
    *, endpoint_url: str, region: str, access_key_id: str, secret_access_key: str
) -> Any:
    import boto3
    from botocore.config import Config

    config = Config(
        signature_version="s3v4",
        # S3-compatible services (Supabase, R2, MinIO) are addressed by path, not by
        # bucket subdomain.
        s3={"addressing_style": "path"},
        retries={"max_attempts": 3, "mode": "standard"},
        connect_timeout=10,
        read_timeout=60,
        # Send and verify checksums only when the API requires them. botocore >= 1.36
        # otherwise adds CRC trailers that some S3-compatible services reject.
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
    )
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url or None,
        region_name=region or None,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        config=config,
    )


class S3Storage:
    """Content-addressed blobs in one S3-compatible bucket, keyed ``aa/bb/<sha256>``."""

    def __init__(
        self,
        *,
        bucket: str,
        client: Any | None = None,
        endpoint_url: str = "",
        region: str = "",
        access_key_id: str = "",
        secret_access_key: str = "",
    ) -> None:
        if not bucket:
            raise StorageConfigError("S3_BUCKET must be set when STORAGE_BACKEND=s3")
        if client is None:
            if not access_key_id or not secret_access_key:
                raise StorageConfigError(
                    "S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY must be set when STORAGE_BACKEND=s3"
                )
            client = _build_client(
                endpoint_url=endpoint_url,
                region=region,
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
            )
        self._bucket = bucket
        self._client = client

    def __repr__(self) -> str:  # never shows the client, its endpoint or credentials
        return f"S3Storage(bucket={self._bucket!r})"

    @staticmethod
    def key_for(content_hash: str) -> str:
        """The object key for a content hash. Raises ``ValueError`` for anything that
        is not a 64-character SHA-256 hex digest (no separators, no ``..``)."""
        h = LocalStorage._validate_hash(content_hash)
        return f"{h[:2]}/{h[2:4]}/{h}"

    # --- Storage interface ------------------------------------------------------

    def put(self, content: bytes) -> str:
        content_hash, _ = self.put_stream(io.BytesIO(content))
        return content_hash

    def put_stream(self, fileobj: BinaryIO) -> tuple[str, int]:
        """Hash the stream while spooling it, then upload it under its hash.

        The key is only known once the whole stream is hashed, so the bytes are
        spooled first (memory, then a temp file). Content already stored is not
        uploaded again. A failed upload raises ``StorageUnavailableError`` and leaves
        nothing under the key: a single PUT either stores the whole object or none.
        """
        hasher = hashlib.sha256()
        size = 0
        with tempfile.SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES) as spool:
            while chunk := fileobj.read(CHUNK_SIZE):
                hasher.update(chunk)
                size += len(chunk)
                spool.write(chunk)
            content_hash = hasher.hexdigest()
            if self.exists(content_hash):
                return content_hash, size
            spool.seek(0)
            try:
                self._client.put_object(
                    Bucket=self._bucket,
                    Key=self.key_for(content_hash),
                    Body=spool,
                    ContentLength=size,
                    ContentType="application/octet-stream",
                )
            except Exception as exc:  # noqa: BLE001 - mapped to a generic storage error
                raise _unavailable("upload", exc) from None
        return content_hash, size

    def exists(self, content_hash: str) -> bool:
        key = self.key_for(content_hash)
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except Exception as exc:  # noqa: BLE001 - classified below
            if _is_missing(exc):
                return False
            raise _unavailable("lookup", exc) from None
        return True

    def open(self, content_hash: str) -> BinaryIO:
        key = self.key_for(content_hash)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except Exception as exc:  # noqa: BLE001 - classified below
            if _is_missing(exc):
                raise FileNotFoundError("stored object not found") from None
            raise _unavailable("download", exc) from None
        return _ObjectStream(response["Body"])  # type: ignore[return-value]

    def delete(self, content_hash: str) -> bool:
        """Delete the object. Returns True if an object was removed, False if there
        was none (S3 deletes are idempotent, so existence is checked first)."""
        if not self.exists(content_hash):
            return False
        try:
            self._client.delete_object(Bucket=self._bucket, Key=self.key_for(content_hash))
        except Exception as exc:  # noqa: BLE001 - mapped to a generic storage error
            if _is_missing(exc):
                return False
            raise _unavailable("delete", exc) from None
        return True

    def path_for(self, content_hash: str):  # noqa: ANN201 - Protocol member
        """Objects have no filesystem path. Nothing in the application calls this for
        object storage; it is defined so the class still satisfies ``Storage``."""
        raise NotImplementedError("object storage has no filesystem path; use open()")
