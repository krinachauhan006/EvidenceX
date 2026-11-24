"""Migration 0005 and the analysis runner on a real, file-backed SQLite database
(real commits, savepoints and separate sessions). Never touches var/evidencex.db."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.core.config import Settings
from app.core.database import Base, build_engine
from app.modules.analysis import extract
from app.modules.analysis.models import AnalysisRun, Claim, PotentialContradiction
from app.modules.analysis.runner import AnalysisRunner, RuleBasedClaimExtractor
from app.modules.cases.models import Case
from app.modules.evidence.models import Evidence
from app.modules.processing.models import Extraction, ExtractionSegment

BACKEND_DIR = Path(__file__).resolve().parents[2]
ANALYSIS_TABLES = {
    "analysis_runs",
    "claims",
    "entities",
    "claim_entities",
    "claim_relationships",
    "contradictions",
    "alternative_explanations",
    "review_actions",
    "segment_reviews",
}


def _cfg(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["sqlalchemy_url"] = url
    return cfg


@pytest.fixture
def db_url(tmp_path) -> str:
    return f"sqlite+pysqlite:///{(tmp_path / 'analysis.db').as_posix()}"


@pytest.fixture
def engine(db_url):
    command.upgrade(_cfg(db_url), "head")
    eng = build_engine(Settings(DATABASE_URL=db_url))
    yield eng
    eng.dispose()


def test_migration_matches_models_and_downgrades(db_url, engine):
    insp = inspect(engine)
    assert ANALYSIS_TABLES <= set(insp.get_table_names())
    for name in ANALYSIS_TABLES:
        model_cols = {c.name for c in Base.metadata.tables[name].columns}
        db_cols = {c["name"] for c in insp.get_columns(name)}
        assert model_cols == db_cols, name
    engine.dispose()
    command.downgrade(_cfg(db_url), "0004_create_extractions")
    eng = build_engine(Settings(DATABASE_URL=db_url))
    try:
        remaining = set(inspect(eng).get_table_names())
        assert not (ANALYSIS_TABLES & remaining)
        assert {"cases", "evidence", "extractions", "extraction_segments"} <= remaining
    finally:
        eng.dispose()
    command.upgrade(_cfg(db_url), "head")


def _seed(db: Session, name: str, case: Case, rows: list[tuple[str, str]]) -> Evidence:
    ev = Evidence(
        case_id=case.id,
        original_filename=name,
        evidence_type="tabular",
        mime_type="text/csv",
        byte_size=10,
        sha256=name[0] * 64,
        storage_path="x",
        processing_status="completed",
        processing_attempts=1,
    )
    db.add(ev)
    db.flush()
    ex = Extraction(
        evidence_id=ev.id,
        case_id=case.id,
        run_number=1,
        run_status="completed",
        is_current=True,
        extractor="csv",
        extractor_version="1",
        source_sha256=ev.sha256,
        outcome="ok",
        doc_metadata={},
        warnings=[],
        segment_count=len(rows),
        duration_ms=1,
    )
    db.add(ex)
    db.flush()
    for i, (ident, time) in enumerate(rows):
        cells = [
            {"column": "shipment_id", "value": ident, "type_hint": "text"},
            {"column": "arrival_time", "value": time, "type_hint": "text"},
        ]
        db.add(
            ExtractionSegment(
                extraction_id=ex.id,
                evidence_id=ev.id,
                case_id=case.id,
                seq=i,
                segment_type="table_row",
                text=f"shipment_id: {ident} | arrival_time: {time}",
                data={"cells": cells},
                locator={"kind": "csv", "row": i + 2},
            )
        )
    return ev


class _FailsFor(RuleBasedClaimExtractor):
    def __init__(self, marker: str) -> None:
        self.marker = marker

    def extract(self, segments):
        drafts = extract.extract_claims(segments)
        if any(self.marker in (s.text or "") for s in segments):
            # The claim row is flushed first; the entity insert then violates NOT NULL.
            # The savepoint must undo the already-flushed claim too.
            for d in drafts:
                for m in d.mentions:
                    m.normalized_key = None  # type: ignore[assignment]
        return drafts


def test_one_failing_item_does_not_affect_others(engine):
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions() as db:
        case = Case(title="Isolation", description=None, status="open")
        db.add(case)
        db.flush()
        good_a = _seed(db, "a.csv", case, [("NS-1001", "10:00")])
        good_b = _seed(db, "b.csv", case, [("NS-1001", "15:00")])
        bad = _seed(db, "c.csv", case, [("NS-9999", "BOOM 11:00")])
        run = AnalysisRun(case_id=case.id, status="running", method="rule_based_v1", stats={})
        db.add(run)
        db.commit()
        case_id, run_id = case.id, run.id

    @contextmanager
    def factory():
        with sessions() as s:
            yield s

    AnalysisRunner(session_factory=factory, settings=Settings(), extractor=_FailsFor("BOOM")).run(
        case_id, run_id
    )

    with sessions() as db:
        run = db.get(AnalysisRun, run_id)
        assert run.status == "completed"
        assert run.stats["evidence_analysed"] == 2
        assert [e["evidence_id"] for e in run.stats["errors"]] == [str(bad.id)]
        assert run.stats["errors"][0]["error_type"] == "IntegrityError"
        per_ev = dict(
            db.execute(select(Claim.evidence_id, func.count()).group_by(Claim.evidence_id)).all()
        )
        assert per_ev == {good_a.id: 1, good_b.id: 1}
        (c,) = db.scalars(select(PotentialContradiction)).all()
        assert {c.claim_a_id, c.claim_b_id} == set(db.scalars(select(Claim.id)).all())
