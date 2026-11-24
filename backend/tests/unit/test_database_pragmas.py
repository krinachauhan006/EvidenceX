"""SQLite hardening applied to file databases by ``build_engine``."""

from __future__ import annotations

from app.core.config import Settings
from app.core.database import build_engine


def _engine(path):
    return build_engine(Settings(DATABASE_URL=f"sqlite+pysqlite:///{path.as_posix()}"))


def test_file_sqlite_gets_wal_foreign_keys_and_busy_timeout(tmp_path):
    engine = _engine(tmp_path / "t.db")
    try:
        with engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"
            assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 15000
    finally:
        engine.dispose()


def test_in_memory_sqlite_skips_wal_but_keeps_foreign_keys():
    engine = build_engine(Settings(DATABASE_URL="sqlite+pysqlite:///:memory:"))
    try:
        with engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            assert conn.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "memory"
    finally:
        engine.dispose()
