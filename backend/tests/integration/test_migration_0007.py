"""Migration 0007 (Phase 2) on a database holding Phase 1 data.

Checks that the upgrade keeps every existing row unchanged, adds no memberships (so no
account can see the old cases by accident), that downgrade restores the exact Phase 1
state, and that the old cases go to the operator-designated account only.
"""

from __future__ import annotations

import importlib.util
import uuid

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import Settings
from app.core.database import build_engine
from app.modules.analysis.audit import verify_chain
from app.modules.auth.schemas import RegisterRequest
from app.modules.auth.service import AuthService
from tests.integration.test_migration_schema import BACKEND_DIR, _cfg, _url, seed, snapshot

MIGRATION_0007 = BACKEND_DIR / "alembic" / "versions" / "0007_phase2_auth_events_reports.py"
NEW_TABLES = {"users", "auth_sessions", "case_members", "events", "event_claims", "reports"}


def _columns(url: str, table: str) -> list[str]:
    eng = create_engine(url)
    try:
        with eng.connect() as c:
            return [r[1] for r in c.execute(text(f'PRAGMA table_info("{table}")'))]
    finally:
        eng.dispose()


def _rows(url: str, table: str, cols: list[str]) -> list[tuple]:
    eng = create_engine(url)
    try:
        with eng.connect() as c:
            quoted = ", ".join(f'"{x}"' for x in cols)
            return sorted(map(tuple, c.execute(text(f'SELECT {quoted} FROM "{table}"'))), key=repr)
    finally:
        eng.dispose()


def _scalar(url: str, sql: str):  # noqa: ANN202
    eng = create_engine(url)
    try:
        with eng.connect() as c:
            return c.execute(text(sql)).scalar()
    finally:
        eng.dispose()


def _run_0007_fk_enforced(url: str) -> None:
    spec = importlib.util.spec_from_file_location("m0007", MIGRATION_0007)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    eng = build_engine(Settings(DATABASE_URL=url))
    try:
        with eng.begin() as conn:
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
            ctx = MigrationContext.configure(conn, opts={"render_as_batch": True})
            with Operations.context(ctx):
                mod.upgrade()
            conn.execute(text("UPDATE alembic_version SET version_num='0007_phase2'"))
    finally:
        eng.dispose()


@pytest.fixture
def phase1_db(tmp_path):
    url = _url(tmp_path / "phase1.db")
    command.upgrade(_cfg(url), "0005_create_analysis")
    ids = seed(url)
    command.upgrade(_cfg(url), "0006_analysis_not_null_ts")
    return url, ids, snapshot(url)


@pytest.mark.parametrize("fk_on", [False, True], ids=["alembic-engine", "fk-enforced"])
def test_upgrade_keeps_every_phase1_row_and_adds_no_members(phase1_db, fk_on):
    url, ids, before = phase1_db
    assert before["cases"] and before["claims"] and before["review_actions"]
    if fk_on:
        _run_0007_fk_enforced(url)
    else:
        command.upgrade(_cfg(url), "head")
    assert _scalar(url, "SELECT version_num FROM alembic_version") == "0007_phase2"
    for table, rows in before.items():
        old_cols = [c for c in _columns(url, table)][: len(rows[0])] if rows else None
        if rows:
            assert _rows(url, table, old_cols) == rows, table
    for table in NEW_TABLES:
        assert _scalar(url, f'SELECT COUNT(*) FROM "{table}"') == 0, table
    # New columns start in their safe state for old rows.
    assert _scalar(url, "SELECT COUNT(*) FROM cases WHERE ai_processing_allowed != 0") == 0
    assert _scalar(url, "SELECT COUNT(*) FROM claims WHERE superseded_by_run_id IS NOT NULL") == 0
    assert _scalar(url, "SELECT COUNT(*) FROM review_actions WHERE hash IS NOT NULL") == 0


def test_downgrade_restores_the_exact_phase1_state(phase1_db):
    url, _ids, before = phase1_db
    command.upgrade(_cfg(url), "head")
    command.downgrade(_cfg(url), "0006_analysis_not_null_ts")
    assert snapshot(url) == before


def test_old_cases_go_only_to_the_designated_account(phase1_db):
    url, ids, _before = phase1_db
    command.upgrade(_cfg(url), "head")
    case_id = uuid.UUID(ids["case"])
    eng = build_engine(Settings(DATABASE_URL=url))
    try:
        with Session(eng) as db:
            service = AuthService(db, Settings(LEGACY_CASES_OWNER_EMAIL="operator@example.org"))
            stranger, n0 = service.register(
                RegisterRequest(
                    email="first@example.org", display_name="First", password="a long password"
                )
            )
            assert n0 == 0 and service.membership(case_id, stranger.id) is None
            op, n1 = service.register(
                RegisterRequest(
                    email="operator@example.org", display_name="Op", password="a long password"
                )
            )
            assert n1 == 1 and service.membership(case_id, op.id).role == "owner"
            chain = verify_chain(db, case_id)
            # Phase 1 actions are reported as legacy; the claim itself is chained.
            assert chain["intact"] is True
            assert chain["legacy_unchained"] >= 1 and chain["checked"] == 1
    finally:
        eng.dispose()
    assert _scalar(url, "SELECT COUNT(*) FROM case_members") == 1
