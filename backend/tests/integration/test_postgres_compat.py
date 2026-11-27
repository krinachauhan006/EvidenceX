"""PostgreSQL compatibility: migrations, schema parity with the models, the production
start-up check, /health, and the serverless pool options, against a REAL Postgres.

Skipped unless ``TEST_POSTGRES_ADMIN_URL`` points at a disposable server, e.g.
``postgresql+psycopg://postgres@127.0.0.1:55432/postgres``. Each test creates and
drops its own scratch databases (``evx_t_*``); nothing else on the server is touched.
Never point this at a production database.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

import app.main as main_module
from alembic import command
from app.core.config import Settings
from app.core.database import Base, build_engine
from app.core.schema import expected_revision, schema_state
from app.main import check_schema_for_production, create_app
from tests.integration.test_migration_schema import _cfg, describe

ADMIN_URL = os.environ.get("TEST_POSTGRES_ADMIN_URL", "")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL.startswith("postgresql"), reason="TEST_POSTGRES_ADMIN_URL not set"
)


@contextmanager
def scratch_db() -> Iterator[str]:
    name = f"evx_t_{uuid.uuid4().hex[:10]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def test_migrations_build_exactly_the_model_schema_on_postgres():
    with scratch_db() as migrated, scratch_db() as reference:
        command.upgrade(_cfg(migrated), "head")
        eng = create_engine(reference, poolclass=NullPool)
        Base.metadata.create_all(eng)
        eng.dispose()
        got, want = describe(migrated), describe(reference)
        assert len(want) == 19
        assert set(got) == set(want)
        for table in want:
            assert got[table] == want[table], table


def test_downgrade_to_base_and_upgrade_again_on_postgres():
    with scratch_db() as url:
        command.upgrade(_cfg(url), "head")
        command.downgrade(_cfg(url), "base")
        eng = create_engine(url, poolclass=NullPool)
        assert set(inspect(eng).get_table_names()) <= {"alembic_version"}
        eng.dispose()
        command.upgrade(_cfg(url), "head")
        eng = create_engine(url, poolclass=NullPool)
        assert schema_state(eng)["up_to_date"] is True
        eng.dispose()


def test_production_startup_and_health_on_postgres(monkeypatch):
    with scratch_db() as url:
        settings = Settings(APP_ENV="production", COOKIE_SECURE=True, DATABASE_URL=url)
        eng = build_engine(settings)
        try:
            with pytest.raises(Exception, match="alembic upgrade head"):
                check_schema_for_production(settings, db_engine=eng)  # empty database
            command.upgrade(_cfg(url), "head")
            check_schema_for_production(settings, db_engine=eng)
            monkeypatch.setattr(main_module, "engine", eng)
            with TestClient(create_app(settings)) as client:
                body = client.get("/health").json()
            assert body["status"] == "ok" and body["database"] == "ok"
            assert body["schema"] == {
                "revision": expected_revision(),
                "expected": expected_revision(),
                "up_to_date": True,
            }
        finally:
            eng.dispose()


def test_health_reports_a_pending_migration_on_postgres(monkeypatch):
    with scratch_db() as url:
        command.upgrade(_cfg(url), "0006_analysis_not_null_ts")
        settings = Settings(DATABASE_URL=url)  # development: starts, health says behind
        eng = build_engine(settings)
        try:
            monkeypatch.setattr(main_module, "engine", eng)
            with TestClient(create_app(settings)) as client:
                body = client.get("/health").json()
            assert body["status"] == "degraded" and body["database"] == "migration_required"
            assert body["schema"]["up_to_date"] is False
        finally:
            eng.dispose()


def test_transaction_pooler_mode_runs_repeated_queries_without_prepared_statements():
    with scratch_db() as url:
        eng = build_engine(Settings(DATABASE_URL=url, DATABASE_TRANSACTION_POOLER=True))
        try:
            assert isinstance(eng.pool, NullPool)
            with eng.connect() as c:
                for i in range(12):  # psycopg prepares after 5 executions by default
                    assert c.execute(text("SELECT :n + 1"), {"n": i}).scalar() == i + 1
                assert c.connection.dbapi_connection.prepare_threshold is None
        finally:
            eng.dispose()


def test_default_pool_is_small_and_pre_pings():
    with scratch_db() as url:
        eng = build_engine(Settings(DATABASE_URL=url))
        try:
            assert eng.pool.size() == 2 and eng.pool._pre_ping
            with eng.connect() as c:
                assert c.execute(text("SELECT 1")).scalar() == 1
        finally:
            eng.dispose()
