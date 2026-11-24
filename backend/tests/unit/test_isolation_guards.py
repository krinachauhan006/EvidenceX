"""The test run itself must be isolated from the live database and storage.

``tests/__init__.py`` points the application at an in-memory database and a
throwaway storage folder before the app is imported. These tests fail loudly if that
ever stops being true, because every other test relies on it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.core.config import get_settings
from app.core.database import engine
from tests.fixtures.blob_control import BACKEND_DIR


def _within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def test_application_settings_use_a_throwaway_database():
    assert get_settings().database_url == "sqlite+pysqlite:///:memory:"


def test_default_engine_is_in_memory_not_the_live_file():
    assert engine.url.database in (None, "", ":memory:")


def test_application_storage_root_is_a_temporary_directory():
    root = Path(get_settings().storage_root)
    assert _within(root, Path(tempfile.gettempdir()))
    assert not _within(root, BACKEND_DIR)


def test_live_paths_are_not_what_the_settings_point_at():
    live_storage = (BACKEND_DIR / "var" / "storage").resolve()
    live_database = (BACKEND_DIR / "var" / "evidencex.db").resolve()
    assert Path(get_settings().storage_root).resolve() != live_storage
    assert str(live_database) not in get_settings().database_url
