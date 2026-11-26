"""A database older than the code is reported clearly instead of as an opaque 500.

The cause of a real failure: the server ran against a database still at revision
0006, which has no ``users`` table, so every sign-in and registration raised
"no such table" and answered 500. These tests pin the clear 503, the /health
report, and that nothing about it leaks passwords or SQL.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from alembic import command
from app.core.database import get_db
from app.core.exceptions import _database_error_handler
from app.core.schema import (
    SCHEMA_OUTDATED_MESSAGE,
    expected_revision,
    is_missing_schema_error,
    schema_state,
)
from app.main import create_app
from tests.integration.test_migration_schema import _cfg, _url


@pytest.fixture
def empty_db_client() -> Iterator[TestClient]:
    """The real app on a database WITHOUT the Phase 2 tables (like an un-migrated 0006)."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as c:
        c.execute(text("CREATE TABLE cases (id TEXT PRIMARY KEY, title TEXT)"))
    factory = sessionmaker(bind=engine)
    app = create_app()

    def _db() -> Iterator[Session]:
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    with TestClient(app) as c:
        yield c
    engine.dispose()


def _sqlite_error(sql: str) -> OperationalError:
    eng = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with eng.connect() as c:
            c.execute(text(sql))
    except OperationalError as exc:
        return exc
    finally:
        eng.dispose()
    raise AssertionError("expected an OperationalError")


def test_missing_table_and_column_are_recognised():
    assert is_missing_schema_error(_sqlite_error("SELECT * FROM users"))
    eng = create_engine("sqlite+pysqlite:///:memory:")
    with eng.connect() as c:
        c.execute(text("CREATE TABLE t (a INTEGER)"))
        with pytest.raises(OperationalError) as info:
            c.execute(text("SELECT b FROM t"))
    eng.dispose()
    assert is_missing_schema_error(info.value)


def test_other_database_errors_are_not_disguised():
    locked = OperationalError("SELECT 1", {}, sqlite3.OperationalError("database is locked"))
    assert not is_missing_schema_error(locked)
    assert not is_missing_schema_error(_sqlite_error("SELEKT 1"))
    with pytest.raises(OperationalError):  # re-raised: stays a 500, as before
        asyncio.run(_database_error_handler(None, locked))  # type: ignore[arg-type]


def test_sign_in_on_an_unmigrated_database_answers_503_with_the_fix(empty_db_client):
    secret = "a-secret-passphrase-42"
    r = empty_db_client.post(
        "/api/auth/login", json={"email": "someone@example.org", "password": secret}
    )
    assert r.status_code == 503
    assert r.json() == {"detail": SCHEMA_OUTDATED_MESSAGE}
    assert "alembic upgrade head" in r.json()["detail"]
    assert secret not in r.text and "someone@example.org" not in r.text
    assert "SELECT" not in r.text and "no such table" not in r.text


def test_registration_on_an_unmigrated_database_answers_503(empty_db_client):
    r = empty_db_client.post(
        "/api/auth/register",
        json={"email": "new@example.org", "display_name": "N", "password": "long enough"},
    )
    assert r.status_code == 503 and "alembic upgrade head" in r.json()["detail"]
    # The password rule is still checked first and still answers 400.
    weak = empty_db_client.post(
        "/api/auth/register",
        json={"email": "new@example.org", "display_name": "N", "password": "short"},
    )
    assert weak.status_code == 400


def test_schema_state_reports_behind_current_and_unknown(tmp_path):
    head = expected_revision()
    assert head and head.startswith("0007")
    url = _url(tmp_path / "db.sqlite")
    command.upgrade(_cfg(url), "0006_analysis_not_null_ts")
    eng = create_engine(url)
    try:
        assert schema_state(eng) == {
            "revision": "0006_analysis_not_null_ts",
            "expected": head,
            "up_to_date": False,
        }
        command.upgrade(_cfg(url), "head")
        assert schema_state(eng)["up_to_date"] is True
    finally:
        eng.dispose()
    bare = create_engine("sqlite+pysqlite:///:memory:")
    assert schema_state(bare) == {"revision": None, "expected": head, "up_to_date": None}
    bare.dispose()


def test_health_includes_the_schema_state(client):
    body = client.get("/health").json()
    assert set(body["schema"]) == {"revision", "expected", "up_to_date"}
    # The test database is built without Alembic, so its revision is unknown, not "behind".
    assert body["schema"]["up_to_date"] is None and body["database"] == "ok"
