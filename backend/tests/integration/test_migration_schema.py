"""Migration chain vs ORM models, and migration 0006 (NOT NULL timestamps).

Every test builds its own throwaway SQLite files under ``tmp_path``. Nothing here
touches ``var/evidencex.db``.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.core.config import Settings
from app.core.database import Base, build_engine

# Register every model on Base.metadata.
from app.modules.analysis import models as _analysis  # noqa: F401
from app.modules.cases import models as _cases  # noqa: F401
from app.modules.evidence import models as _evidence  # noqa: F401
from app.modules.processing import models as _processing  # noqa: F401

BACKEND_DIR = Path(__file__).resolve().parents[2]
MIGRATION_0006 = BACKEND_DIR / "alembic" / "versions" / "0006_analysis_not_null_timestamps.py"
FIXED = [
    ("analysis_runs", "started_at"),
    ("claim_entities", "created_at"),
    ("alternative_explanations", "created_at"),
    ("review_actions", "created_at"),
    ("segment_reviews", "created_at"),
]
TS = "2026-11-19 10:00:00.000000"


def _cfg(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["sqlalchemy_url"] = url
    return cfg


def _url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path.as_posix()}"


def _hex() -> str:
    return uuid.uuid4().hex


def describe(url: str) -> dict[str, Any]:
    """Comparable schema description (server defaults deliberately excluded)."""
    eng = create_engine(url)
    try:
        insp = inspect(eng)
        out: dict[str, Any] = {}
        for t in sorted(insp.get_table_names()):
            if t == "alembic_version":
                continue
            out[t] = {
                "columns": sorted(
                    (c["name"], str(c["type"]), bool(c["nullable"])) for c in insp.get_columns(t)
                ),
                "pk": sorted(insp.get_pk_constraint(t)["constrained_columns"]),
                "fks": sorted(
                    (
                        tuple(f["constrained_columns"]),
                        f["referred_table"],
                        tuple(f["referred_columns"]),
                        (f.get("options") or {}).get("ondelete", "").upper(),
                    )
                    for f in insp.get_foreign_keys(t)
                ),
                "indexes": sorted(
                    (i["name"], tuple(i["column_names"]), bool(i["unique"]))
                    for i in insp.get_indexes(t)
                ),
                "uniques": sorted(
                    tuple(sorted(u["column_names"])) for u in insp.get_unique_constraints(t)
                ),
            }
        return out
    finally:
        eng.dispose()


def notnull(url: str, table: str, column: str) -> bool:
    eng = create_engine(url)
    try:
        with eng.connect() as c:
            rows = c.execute(text(f'PRAGMA table_info("{table}")')).fetchall()
        return next(bool(r[3]) for r in rows if r[1] == column)
    finally:
        eng.dispose()


# --- seed data at revision 0005 (raw SQL, so it does not depend on the ORM) ---------


def seed(url: str) -> dict[str, str]:
    eng = build_engine(Settings(DATABASE_URL=url))  # FK enforcement ON
    ids = {
        k: _hex()
        for k in (
            "case",
            "ev",
            "ex",
            "seg",
            "run",
            "claim_a",
            "claim_b",
            "ent",
            "ce",
            "rel",
            "con",
            "alt",
            "ra",
            "sr",
        )
    }
    stamps = {"created_at": TS, "updated_at": TS}
    sha = "a" * 64
    rows: list[tuple[str, dict[str, Any]]] = [
        ("cases", {"id": ids["case"], "title": "C", "status": "open", **stamps}),
        (
            "evidence",
            {
                "id": ids["ev"],
                "case_id": ids["case"],
                "original_filename": "a.csv",
                "evidence_type": "tabular",
                "mime_type": "text/csv",
                "byte_size": 1,
                "sha256": sha,
                "storage_path": "x",
                "processing_status": "completed",
                "processing_attempts": 1,
                **stamps,
            },
        ),
        (
            "extractions",
            {
                "id": ids["ex"],
                "evidence_id": ids["ev"],
                "case_id": ids["case"],
                "run_number": 1,
                "run_status": "completed",
                "is_current": 1,
                "extractor": "csv",
                "extractor_version": "1",
                "source_sha256": sha,
                "outcome": "ok",
                "doc_metadata": "{}",
                "warnings": "[]",
                "segment_count": 1,
                "duration_ms": 1,
                "started_at": TS,
                **stamps,
            },
        ),
        (
            "extraction_segments",
            {
                "id": ids["seg"],
                "extraction_id": ids["ex"],
                "evidence_id": ids["ev"],
                "case_id": ids["case"],
                "seq": 0,
                "segment_type": "table_row",
                "text": "t",
                "locator": '{"kind":"csv"}',
                "created_at": TS,
            },
        ),
        (
            "analysis_runs",
            {
                "id": ids["run"],
                "case_id": ids["case"],
                "status": "completed",
                "method": "rule_based_v1",
                "started_at": TS,
                "stats": "{}",
                **stamps,
            },
        ),
    ]
    for key in ("claim_a", "claim_b"):
        rows.append(
            (
                "claims",
                {
                    "id": ids[key],
                    "case_id": ids["case"],
                    "evidence_id": ids["ev"],
                    "extraction_id": ids["ex"],
                    "segment_id": ids["seg"],
                    "analysis_run_id": ids["run"],
                    "claim_text": "t",
                    "claim_type": "date_time",
                    "quote": "t",
                    "modality": "tabular",
                    "grounding": "grounded",
                    "extraction_method": "rule_based_v1",
                    "is_inferred": 0,
                    "uncertainty": "[]",
                    "review_status": "unreviewed",
                    "dedupe_key": key,
                    **stamps,
                },
            )
        )
    rows += [
        (
            "entities",
            {
                "id": ids["ent"],
                "case_id": ids["case"],
                "entity_type": "shipment",
                "display_name": "NS-1",
                "normalized_key": "NS1",
                "aliases": "[]",
                "resolution_status": "unresolved",
                "review_status": "unreviewed",
                **stamps,
            },
        ),
        (
            "claim_entities",
            {
                "id": ids["ce"],
                "case_id": ids["case"],
                "claim_id": ids["claim_a"],
                "entity_id": ids["ent"],
                "mention_text": "NS-1",
                "created_at": TS,
            },
        ),
        (
            "claim_relationships",
            {
                "id": ids["rel"],
                "case_id": ids["case"],
                "source_claim_id": ids["claim_a"],
                "target_claim_id": ids["claim_b"],
                "via_entity_id": ids["ent"],
                "relation_type": "mentions_same_entity",
                "rationale": "r",
                "origin": "rule_based_v1",
                "review_status": "unreviewed",
                **stamps,
            },
        ),
        (
            "contradictions",
            {
                "id": ids["con"],
                "case_id": ids["case"],
                "claim_a_id": ids["claim_a"],
                "claim_b_id": ids["claim_b"],
                "via_entity_id": ids["ent"],
                "category": "temporal",
                "explanation": "{}",
                "severity": "high",
                "detection_confidence": 0.5,
                "uncertainty": "[]",
                "origin": "rule_based_v1",
                "review_status": "unreviewed",
                "linked_evidence_ids": "[]",
                **stamps,
            },
        ),
        (
            "alternative_explanations",
            {
                "id": ids["alt"],
                "case_id": ids["case"],
                "contradiction_id": ids["con"],
                "explanation": "e",
                "basis": "machine_hypothesis",
                "status": "proposed",
                "created_at": TS,
            },
        ),
        (
            "review_actions",
            {
                "id": ids["ra"],
                "case_id": ids["case"],
                "target_type": "claim",
                "target_id": ids["claim_a"],
                "action": "verify",
                "payload": "{}",
                "created_at": TS,
            },
        ),
        (
            "segment_reviews",
            {
                "id": ids["sr"],
                "case_id": ids["case"],
                "evidence_id": ids["ev"],
                "segment_id": ids["seg"],
                "corrected_text": "fixed",
                "created_at": TS,
            },
        ),
    ]
    try:
        with eng.begin() as c:
            for table, values in rows:
                insert(c, table, values)
    finally:
        eng.dispose()
    return ids


def insert(conn: Any, table: str, values: dict[str, Any]) -> None:
    cols = ", ".join(values)
    marks = ", ".join(f":{k}" for k in values)
    conn.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({marks})"), values)


def snapshot(url: str) -> dict[str, list]:
    eng = create_engine(url)
    try:
        with eng.connect() as c:
            names = [
                r[0]
                for r in c.execute(
                    text(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version' "
                        "ORDER BY name"
                    )
                )
            ]
            return {
                n: sorted(map(tuple, c.execute(text(f'SELECT * FROM "{n}"')).fetchall()), key=repr)
                for n in names
            }
    finally:
        eng.dispose()


def run_0006_with_fk_enforcement(url: str, direction: str) -> None:
    """Run 0006 on a connection with PRAGMA foreign_keys=ON (the app's setting)."""
    spec = importlib.util.spec_from_file_location("m0006", MIGRATION_0006)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    eng = build_engine(Settings(DATABASE_URL=url))
    try:
        with eng.begin() as conn:
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
            ctx = MigrationContext.configure(conn, opts={"render_as_batch": True})
            with Operations.context(ctx):
                getattr(mod, direction)()
    finally:
        eng.dispose()


# --- tests ---------------------------------------------------------------------------


def test_migrated_schema_matches_models_exactly(tmp_path):
    migrated = _url(tmp_path / "migrated.db")
    command.upgrade(_cfg(migrated), "head")
    reference = _url(tmp_path / "reference.db")
    eng = create_engine(reference)
    Base.metadata.create_all(eng)
    eng.dispose()
    got, want = describe(migrated), describe(reference)
    assert len(want) == 9 + 4 and {"claims", "cases", "extraction_segments"} <= set(want)
    assert set(got) == set(want)
    for table in want:
        assert got[table] == want[table], table


def test_comparison_detects_the_0005_drift(tmp_path):
    """Negative control: at 0005 the comparison finds exactly the five known columns."""
    at_0005 = _url(tmp_path / "old.db")
    command.upgrade(_cfg(at_0005), "0005_create_analysis")
    reference = _url(tmp_path / "ref.db")
    eng = create_engine(reference)
    Base.metadata.create_all(eng)
    eng.dispose()
    got, want = describe(at_0005), describe(reference)
    differing = set()
    for table in want:
        for (name, ty, nl), (name2, ty2, nl2) in zip(
            got[table]["columns"], want[table]["columns"], strict=True
        ):
            assert (name, ty) == (name2, ty2)
            if nl != nl2:
                differing.add((table, name))
        assert {k: v for k, v in got[table].items() if k != "columns"} == {
            k: v for k, v in want[table].items() if k != "columns"
        }, table
    assert differing == set(FIXED)


def test_head_is_0006(tmp_path):
    url = _url(tmp_path / "h.db")
    command.upgrade(_cfg(url), "head")
    eng = create_engine(url)
    with eng.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == (
            "0006_analysis_not_null_ts"
        )
    eng.dispose()


@pytest.mark.parametrize("fk_on", [False, True], ids=["alembic-engine", "fk-enforced"])
def test_0006_preserves_rows_constraints_and_links(tmp_path, fk_on):
    url = _url(tmp_path / "data.db")
    command.upgrade(_cfg(url), "0005_create_analysis")
    ids = seed(url)
    before_rows, before_schema = snapshot(url), describe(url)
    for t, col in FIXED:
        assert not notnull(url, t, col)

    if fk_on:
        run_0006_with_fk_enforcement(url, "upgrade")
        eng = create_engine(url)
        with eng.begin() as c:
            c.execute(text("UPDATE alembic_version SET version_num='0006_analysis_not_null_ts'"))
        eng.dispose()
    else:
        command.upgrade(_cfg(url), "0006_analysis_not_null_ts")

    assert snapshot(url) == before_rows  # every row and value identical
    after_schema = describe(url)
    for table, desc in before_schema.items():
        expected = desc
        if table in dict(FIXED):
            col = dict(FIXED)[table]
            expected = {
                **desc,
                "columns": sorted(
                    (n, ty, False if n == col else nl) for n, ty, nl in desc["columns"]
                ),
            }
        assert after_schema[table] == expected, table
    for t, col in FIXED:
        assert notnull(url, t, col), (t, col)
    eng = build_engine(Settings(DATABASE_URL=url))
    with eng.connect() as c:
        assert c.execute(text("PRAGMA foreign_key_check")).fetchall() == []
        assert c.execute(text("PRAGMA integrity_check")).scalar() == "ok"
        runs = {r[0] for r in c.execute(text("SELECT analysis_run_id FROM claims"))}
        assert runs == {ids["run"]}  # the SET NULL hazard did not fire
    eng.dispose()


def test_0006_columns_reject_null(tmp_path):
    url = _url(tmp_path / "n.db")
    command.upgrade(_cfg(url), "head")
    ids = seed(url)
    case = ids["case"]
    # Otherwise-valid rows (all foreign keys exist); only the fixed column is NULL.
    attempts: dict[str, tuple[str, dict[str, Any]]] = {
        "analysis_runs.started_at": (
            "analysis_runs",
            {
                "id": _hex(),
                "case_id": case,
                "status": "running",
                "method": "m",
                "started_at": None,
                "stats": "{}",
                "created_at": TS,
                "updated_at": TS,
            },
        ),
        "claim_entities.created_at": (
            "claim_entities",
            {
                "id": _hex(),
                "case_id": case,
                "claim_id": ids["claim_b"],
                "entity_id": ids["ent"],
                "mention_text": "x",
                "created_at": None,
            },
        ),
        "alternative_explanations.created_at": (
            "alternative_explanations",
            {
                "id": _hex(),
                "case_id": case,
                "contradiction_id": ids["con"],
                "explanation": "e",
                "basis": "human",
                "status": "proposed",
                "created_at": None,
            },
        ),
        "review_actions.created_at": (
            "review_actions",
            {
                "id": _hex(),
                "case_id": case,
                "target_type": "claim",
                "target_id": ids["claim_b"],
                "action": "note",
                "payload": "{}",
                "created_at": None,
            },
        ),
        "segment_reviews.created_at": (
            "segment_reviews",
            {
                "id": _hex(),
                "case_id": case,
                "evidence_id": ids["ev"],
                "segment_id": ids["seg"],
                "corrected_text": "x",
                "created_at": None,
            },
        ),
    }
    eng = build_engine(Settings(DATABASE_URL=url))
    try:
        for name, (table, values) in attempts.items():
            with pytest.raises(IntegrityError, match="NOT NULL") as exc:
                with eng.begin() as c:
                    insert(c, table, values)
            assert name in str(exc.value), name
            # Control: the same row with a timestamp is accepted.
            column = name.split(".")[1]
            with eng.begin() as c:
                insert(c, table, {**values, column: TS})
    finally:
        eng.dispose()


@pytest.mark.parametrize("fk_on", [False, True], ids=["alembic-engine", "fk-enforced"])
def test_0006_downgrade_restores_nullable_and_keeps_data(tmp_path, fk_on):
    url = _url(tmp_path / "d.db")
    command.upgrade(_cfg(url), "head")
    ids = seed(url)
    rows = snapshot(url)
    if fk_on:
        run_0006_with_fk_enforcement(url, "downgrade")
    else:
        command.downgrade(_cfg(url), "0005_create_analysis")
    for t, col in FIXED:
        assert not notnull(url, t, col)
    assert snapshot(url) == rows
    eng = build_engine(Settings(DATABASE_URL=url))
    with eng.connect() as c:
        assert c.execute(text("PRAGMA foreign_key_check")).fetchall() == []
        assert {r[0] for r in c.execute(text("SELECT analysis_run_id FROM claims"))} == {ids["run"]}
    eng.dispose()


def test_0006_backfills_started_at_and_refuses_to_invent_created_at(tmp_path):
    url = _url(tmp_path / "b.db")
    command.upgrade(_cfg(url), "0005_create_analysis")
    ids = seed(url)
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text("UPDATE analysis_runs SET started_at=NULL"))
    eng.dispose()
    command.upgrade(_cfg(url), "head")
    eng = create_engine(url)
    with eng.connect() as c:
        row = c.execute(text("SELECT started_at, created_at FROM analysis_runs")).one()
        assert row[0] == row[1] == TS
    eng.dispose()

    url2 = _url(tmp_path / "b2.db")
    command.upgrade(_cfg(url2), "0005_create_analysis")
    seed(url2)
    eng = create_engine(url2)
    with eng.begin() as c:
        c.execute(text("UPDATE review_actions SET created_at=NULL"))
    eng.dispose()
    with pytest.raises(RuntimeError, match="refusing to invent"):
        command.upgrade(_cfg(url2), "head")
    assert not notnull(url2, "review_actions", "created_at")
    assert ids  # seed ran
