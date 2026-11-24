"""The test-only blob helper: behaviour and, above all, its safety guard.

Guard tests never touch the filesystem outside pytest's temporary directory. The
"live" paths below are only ever passed to pure path checks or to stub objects that
cannot perform I/O.
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pytest

from app.storage.local_store import LocalStorage
from tests.fixtures.blob_control import (
    BACKEND_DIR,
    UnsafeStorageError,
    assert_safe_root,
    hidden_blob,
    hide_blob,
    restore_blob,
)

LIVE_STORAGE = BACKEND_DIR / "var" / "storage"
LIVE_DATABASE = BACKEND_DIR / "var" / "evidencex.db"


class _StubStorage:
    """Looks like LocalStorage to the helper but cannot perform any I/O."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def path_for(self, sha256: str) -> Path:
        return self._root / sha256[:2] / sha256[2:4] / sha256


SHA = "ab" * 32


# --- the guard ----------------------------------------------------------------------


def test_temp_directories_are_accepted(tmp_path):
    assert assert_safe_root(tmp_path / "blobs") == (tmp_path / "blobs").resolve()


@pytest.mark.parametrize(
    "path",
    [LIVE_STORAGE, LIVE_DATABASE, BACKEND_DIR, BACKEND_DIR / "tests" / "anything"],
    ids=["live-storage", "live-database", "backend-dir", "inside-backend"],
)
def test_paths_inside_the_backend_are_refused(path):
    with pytest.raises(UnsafeStorageError):
        assert_safe_root(path)


@pytest.mark.parametrize(
    "path",
    [Path.home(), Path.home() / "Documents", BACKEND_DIR.parent, Path(Path.home().anchor)],
    ids=["home", "documents", "repo-root", "drive-root"],
)
def test_paths_outside_the_temp_directory_are_refused(path):
    # Guard: the test environment's temp dir must not itself be one of these.
    temp = Path(tempfile.gettempdir()).resolve()
    if path.resolve() == temp or temp in path.resolve().parents:
        pytest.skip("temp directory overlaps this probe path on this machine")
    with pytest.raises(UnsafeStorageError):
        assert_safe_root(path)


def test_hide_refuses_live_storage_before_any_filesystem_access():
    stub = _StubStorage(LIVE_STORAGE)
    for action in (hide_blob, restore_blob):
        with pytest.raises(UnsafeStorageError):
            action(stub, SHA)
    with pytest.raises(UnsafeStorageError), hidden_blob(stub, SHA):
        pytest.fail("the guarded block must never run")
    # Nothing was created next to the (possibly non-existent) probe path.
    assert not stub.path_for(SHA).exists()
    assert not stub.path_for(SHA).with_name(SHA + ".hold").exists()


def test_helper_refuses_objects_with_no_inspectable_root():
    class NoRoot:
        def path_for(self, sha256: str) -> Path:  # pragma: no cover - never reached
            raise AssertionError("must not be called")

    with pytest.raises(UnsafeStorageError):
        hide_blob(NoRoot(), SHA)  # type: ignore[arg-type]


def test_invalid_hash_is_rejected_by_the_storage_layer(tmp_path):
    storage = LocalStorage(tmp_path / "blobs")
    with pytest.raises(ValueError):
        hide_blob(storage, "../../etc/passwd")


# --- behaviour ----------------------------------------------------------------------


@pytest.fixture
def stored(tmp_path):
    storage = LocalStorage(tmp_path / "blobs")
    data = b"id,note\n1,alpha\n"
    sha, _ = storage.put_stream(io.BytesIO(data))
    return storage, sha, data


def test_hide_and_restore_round_trip(stored):
    storage, sha, data = stored
    hold = hide_blob(storage, sha)
    assert storage.exists(sha) is False
    assert hold.read_bytes() == data  # renamed, never deleted

    restored = restore_blob(storage, sha)
    assert storage.exists(sha) is True
    assert restored.read_bytes() == data
    assert not hold.exists()


def test_context_manager_restores_on_normal_exit(stored):
    storage, sha, data = stored
    with hidden_blob(storage, sha):
        assert storage.exists(sha) is False
    assert storage.exists(sha) is True
    with storage.open(sha) as fh:
        assert fh.read() == data


def test_context_manager_restores_even_when_the_block_raises(stored):
    storage, sha, _ = stored
    with pytest.raises(RuntimeError, match="boom"), hidden_blob(storage, sha):
        raise RuntimeError("boom")
    assert storage.exists(sha) is True


def test_hiding_a_missing_or_already_hidden_blob_fails_loudly(stored, tmp_path):
    storage, sha, _ = stored
    with pytest.raises(FileNotFoundError):
        hide_blob(storage, "cd" * 32)
    hide_blob(storage, sha)
    with pytest.raises(FileNotFoundError):  # the blob itself is gone now
        hide_blob(storage, sha)
    restore_blob(storage, sha)


def test_restore_without_a_hidden_copy_fails(stored):
    storage, sha, _ = stored
    with pytest.raises(FileNotFoundError):
        restore_blob(storage, sha)


def test_restore_refuses_to_overwrite_a_blob(stored):
    storage, sha, data = stored
    hold = hide_blob(storage, sha)
    storage.path_for(sha).write_bytes(b"something else")  # a blob reappeared
    with pytest.raises(FileExistsError):
        restore_blob(storage, sha)
    assert hold.read_bytes() == data  # the held bytes are untouched
