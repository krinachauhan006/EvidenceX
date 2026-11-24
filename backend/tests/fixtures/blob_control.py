"""Test-only helper: temporarily hide a stored blob to simulate transient storage loss.

Hiding is a RENAME (``<hash>`` -> ``<hash>.hold``), never a delete, so the bytes are
always recoverable. Restoring renames it back.

Safety guard. This helper can only operate on a storage root that
  1. lives under the operating system's temporary directory, and
  2. is NOT inside the ``backend/`` directory (which holds the live ``var/storage``).
Anything else raises ``UnsafeStorageError`` before any file is touched. The check runs
on the storage root AND on the resolved blob path, so a crafted hash cannot escape it.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.storage.local_store import LocalStorage

BACKEND_DIR = Path(__file__).resolve().parents[2]
HOLD_SUFFIX = ".hold"


class UnsafeStorageError(RuntimeError):
    """The storage location is not a recognised throwaway test location."""


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def assert_safe_root(root: Path) -> Path:
    """Return the resolved path, or raise if it could be live data."""
    resolved = Path(root).resolve()
    if _is_within(resolved, BACKEND_DIR.resolve()):
        raise UnsafeStorageError("refusing to touch a path inside the backend directory")
    if not _is_within(resolved, Path(tempfile.gettempdir()).resolve()):
        raise UnsafeStorageError("refusing to touch a path outside the temporary directory")
    return resolved


def _blob_path(storage: LocalStorage, sha256: str) -> Path:
    root = getattr(storage, "_root", None)  # LocalStorage keeps its root here
    if not isinstance(root, Path):
        raise UnsafeStorageError("storage root cannot be determined")
    assert_safe_root(root)
    path = storage.path_for(sha256)  # validates the hash and stays under the root
    assert_safe_root(path)  # defence in depth
    return path


def _hold_path(path: Path) -> Path:
    return path.with_name(path.name + HOLD_SUFFIX)


def hide_blob(storage: LocalStorage, sha256: str) -> Path:
    """Rename the blob out of sight. Returns the path of the held copy."""
    path = _blob_path(storage, sha256)
    hold = _hold_path(path)
    if not path.is_file():
        raise FileNotFoundError("blob is not present, nothing to hide")
    if hold.exists():
        raise FileExistsError("blob is already hidden")
    path.rename(hold)
    return hold


def restore_blob(storage: LocalStorage, sha256: str) -> Path:
    """Put a hidden blob back. Returns the restored blob path."""
    path = _blob_path(storage, sha256)
    hold = _hold_path(path)
    if not hold.is_file():
        raise FileNotFoundError("no hidden copy to restore")
    if path.exists():
        raise FileExistsError("a blob already exists at the original location")
    hold.rename(path)
    return path


@contextmanager
def hidden_blob(storage: LocalStorage, sha256: str) -> Iterator[None]:
    """Hide the blob for the duration of the block and always restore it."""
    hide_blob(storage, sha256)
    try:
        yield
    finally:
        path = _blob_path(storage, sha256)
        if _hold_path(path).is_file() and not path.exists():
            restore_blob(storage, sha256)
