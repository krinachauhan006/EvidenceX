"""Local, content-addressed evidence storage (Stage 0 stub).

Later specs (evidence-ingestion) wire this into upload endpoints. It is included
now so downstream modules can depend on a stable interface.

Security invariants enforced here:
- Storage paths are derived ONLY from the content hash, never from a user-supplied
  filename, which makes path traversal structurally impossible.
- Uploaded content is never executed; this module only reads and writes bytes.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import BinaryIO, Protocol

# Read/hash/write in 1 MiB chunks so large files are never fully held in memory.
CHUNK_SIZE = 1024 * 1024


class Storage(Protocol):
    """Interface for evidence blob storage."""

    def put(self, content: bytes) -> str:
        """Store bytes and return their content hash (sha256 hex)."""
        ...

    def put_stream(self, fileobj: BinaryIO) -> tuple[str, int]:
        """Stream ``fileobj`` to storage, returning (sha256_hex, byte_size)."""
        ...

    def path_for(self, content_hash: str) -> Path:
        """Return the filesystem path for a stored content hash."""
        ...

    def exists(self, content_hash: str) -> bool:
        """Return whether content with this hash is already stored."""
        ...

    def open(self, content_hash: str) -> BinaryIO:
        """Open the stored blob for streaming reads."""
        ...

    def delete(self, content_hash: str) -> bool:
        """Delete the stored blob. Returns True if a file was removed."""
        ...


def sha256_hex(content: bytes) -> str:
    """Return the sha256 hex digest of the given bytes."""
    return hashlib.sha256(content).hexdigest()


class LocalStorage:
    """Filesystem-backed content-addressed storage.

    Files are stored under ``root/<aa>/<bb>/<full-hash>`` where ``aa``/``bb`` are
    the first two byte-pairs of the hash — a fan-out to avoid huge directories.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_hash(content_hash: str) -> str:
        """Reject anything that is not a 64-char lowercase sha256 hex digest.

        This guarantees the value cannot contain path separators or ``..``.
        """
        h = content_hash.lower()
        if len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
            raise ValueError("invalid content hash")
        return h

    def path_for(self, content_hash: str) -> Path:
        h = self._validate_hash(content_hash)
        target = (self._root / h[:2] / h[2:4] / h).resolve()
        # Defense in depth: the resolved path must stay under the storage root.
        if self._root not in target.parents:
            raise ValueError("resolved path escapes storage root")
        return target

    def put(self, content: bytes) -> str:
        h = sha256_hex(content)
        target = self.path_for(h)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        return h

    def put_stream(self, fileobj: BinaryIO) -> tuple[str, int]:
        """Stream the file to a temp file while hashing, then move it to its
        content-addressed destination.

        Writing to a temp file first and moving into place means the final blob at
        the hash path always matches that hash — a crash mid-write never leaves a
        corrupt file under a valid name. Duplicate content is written once.
        """
        hasher = hashlib.sha256()
        size = 0
        # Temp file lives under the storage root so the final move stays on one
        # filesystem (atomic rename).
        fd, tmp_name = tempfile.mkstemp(dir=self._root, suffix=".part")
        try:
            with os.fdopen(fd, "wb") as tmp:
                while True:
                    chunk = fileobj.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    hasher.update(chunk)
                    size += len(chunk)
                    tmp.write(chunk)
            content_hash = hasher.hexdigest()
            target = self.path_for(content_hash)
            if target.exists():
                # Duplicate content already stored; drop the temp copy.
                os.unlink(tmp_name)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(tmp_name, target)
            return content_hash, size
        except BaseException:
            # Never leave a stray temp file behind on failure.
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise

    def exists(self, content_hash: str) -> bool:
        return self.path_for(content_hash).exists()

    def open(self, content_hash: str) -> BinaryIO:
        return self.path_for(content_hash).open("rb")

    def delete(self, content_hash: str) -> bool:
        target = self.path_for(content_hash)
        if target.exists():
            target.unlink()
            return True
        return False
