"""Business logic for evidence ingestion and management.

Responsibilities:
- Validate uploads (size, emptiness, extension, content signature).
- Store blobs content-addressed via the storage layer.
- Enforce case-level isolation on every read/delete.
- Keep storage and database consistent (no orphan blobs, no record without blob).
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from typing import BinaryIO

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.logging import get_logger
from app.core.zip_safety import ZipLimits
from app.modules.cases.repository import CaseRepository
from app.modules.evidence.models import Evidence
from app.modules.evidence.repository import EvidenceRepository
from app.modules.evidence.validation import (
    SIGNATURE_PREFIX_LEN,
    UnsupportedFileError,
    deep_validate,
    resolve_and_validate,
)
from app.storage.factory import build_storage
from app.storage.local_store import CHUNK_SIZE, Storage

logger = get_logger(__name__)


@dataclass
class EvidenceFileData:
    """Everything needed to stream a download back to the client."""

    stream: BinaryIO
    mime_type: str
    original_filename: str
    byte_size: int


class EvidenceService:
    def __init__(
        self,
        db: Session,
        storage: Storage | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._db = db
        self._repo = EvidenceRepository(db)
        self._cases = CaseRepository(db)
        self._settings = settings or get_settings()
        self._storage = storage or build_storage(self._settings)

    # --- helpers ----------------------------------------------------------------

    def _require_case(self, case_id: uuid.UUID) -> None:
        if self._cases.get(case_id) is None:
            raise NotFoundError("case not found")

    def _limit_mb(self, filename: str = "") -> int:
        from app.modules.evidence.validation import VIDEO_EXTENSIONS, extension_of

        if extension_of(filename) in VIDEO_EXTENSIONS:
            return self._settings.max_video_upload_mb
        return self._settings.max_upload_size_mb

    def _max_bytes(self, filename: str = "") -> int:
        return self._limit_mb(filename) * 1024 * 1024

    def _buffer_within_limit(self, fileobj: BinaryIO, filename: str = "") -> bytes:
        """Read the whole upload into a bounded in-memory/temp buffer, enforcing
        the size cap while reading so an oversized file is rejected early.

        We buffer to a SpooledTemporaryFile which keeps small files in memory and
        spills large ones to disk, so we never hold a large file fully in RAM.
        """
        max_bytes = self._max_bytes(filename)
        spool = io.BytesIO()
        total = 0
        while True:
            chunk = fileobj.read(CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise BadRequestError(
                    f"file exceeds the maximum upload size of {self._limit_mb(filename)} MB"
                )
            spool.write(chunk)
        if total == 0:
            raise BadRequestError("file is empty")
        spool.seek(0)
        return spool.getvalue()

    # --- operations -------------------------------------------------------------

    def upload(self, case_id: uuid.UUID, *, filename: str, fileobj: BinaryIO) -> Evidence:
        """Validate and store an uploaded file for a case."""
        self._require_case(case_id)

        content = self._buffer_within_limit(fileobj, filename)
        prefix = content[:SIGNATURE_PREFIX_LEN]

        try:
            resolved = resolve_and_validate(filename, prefix)
            deep_validate(filename, content, zip_limits=ZipLimits.from_settings(self._settings))
        except UnsupportedFileError as exc:
            raise BadRequestError(str(exc)) from exc

        # Blob first (idempotent for duplicate content), then the DB record.
        sha256, size = self._storage.put_stream(io.BytesIO(content))

        evidence = Evidence(
            case_id=case_id,
            original_filename=filename[:255],
            evidence_type=resolved.evidence_type,
            mime_type=resolved.mime_type,
            byte_size=size,
            sha256=sha256,
            storage_path=f"{sha256[:2]}/{sha256[2:4]}/{sha256}",
            processing_status="pending",
            processing_error=None,
        )
        try:
            return self._repo.create(evidence)
        except Exception:
            # The record failed to persist. Remove the just-written blob unless
            # another record still references it — never leave an orphan.
            self._db.rollback()
            if self._repo.count_by_hash(sha256) == 0:
                try:
                    self._storage.delete(sha256)
                except OSError:
                    logger.warning("failed to clean up orphan blob %s", sha256)
            raise

    def get(self, case_id: uuid.UUID, evidence_id: uuid.UUID) -> Evidence:
        evidence = self._repo.get_scoped(case_id, evidence_id)
        if evidence is None:
            raise NotFoundError("evidence not found")
        return evidence

    def list_for_case(self, case_id: uuid.UUID) -> tuple[list[Evidence], int]:
        self._require_case(case_id)
        return self._repo.list_for_case(case_id)

    def open_file(self, case_id: uuid.UUID, evidence_id: uuid.UUID) -> EvidenceFileData:
        evidence = self.get(case_id, evidence_id)
        if not self._storage.exists(evidence.sha256):
            raise NotFoundError("stored file is missing")
        return EvidenceFileData(
            stream=self._storage.open(evidence.sha256),
            mime_type=evidence.mime_type,
            original_filename=evidence.original_filename,
            byte_size=evidence.byte_size,
        )

    def delete(self, case_id: uuid.UUID, evidence_id: uuid.UUID) -> None:
        evidence = self.get(case_id, evidence_id)
        sha256 = evidence.sha256
        self._repo.delete(evidence)
        # Remove the blob only if no other record (any case) still references it.
        if self._repo.count_by_hash(sha256) == 0:
            try:
                self._storage.delete(sha256)
            except OSError:
                logger.warning("failed to delete blob %s", sha256)

    def cleanup_case_blobs(self, case_id: uuid.UUID) -> None:
        """Best-effort removal of blobs for a case's evidence that will become
        unreferenced once the case (and its rows, via cascade) is deleted.

        Called by the case-delete flow. Must never raise — a storage hiccup must
        not block deleting the case.
        """
        try:
            hashes = self._repo.hashes_for_case(case_id)
        except Exception:  # noqa: BLE001 - cleanup must not break case deletion
            logger.warning("could not enumerate blobs for case %s", case_id)
            return
        for sha256 in hashes:
            # Delete only if this case's rows are the sole referencers.
            try:
                if self._repo.count_by_hash(sha256) <= self._count_in_case(case_id, sha256):
                    self._storage.delete(sha256)
            except Exception:  # noqa: BLE001
                logger.warning("blob cleanup skipped for %s", sha256)

    def _count_in_case(self, case_id: uuid.UUID, sha256: str) -> int:
        items, _ = self._repo.list_for_case(case_id)
        return sum(1 for e in items if e.sha256 == sha256)
