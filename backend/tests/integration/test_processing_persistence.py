"""File-backed database tests: real migrations, real commits and rollbacks.

The shared-session API tests cannot exercise transaction boundaries (everything
sits inside one outer test transaction). These tests use a throwaway SQLite file
built by Alembic, the production engine settings, and separate sessions.
"""

from __future__ import annotations

import io
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.core.config import Settings
from app.core.database import build_engine
from app.core.db_types import utcnow
from app.modules.cases.models import Case
from app.modules.evidence.models import Evidence
from app.modules.processing import repository as repository_module
from app.modules.processing.errors import CorruptFileError
from app.modules.processing.executor import InlineExecutor
from app.modules.processing.extractors.base import ExtractionResult, SegmentDraft
from app.modules.processing.extractors.csv_extractor import CsvExtractor
from app.modules.processing.locators import CsvLocator
from app.modules.processing.models import Extraction, ExtractionSegment
from app.modules.processing.registry import ExtractorRegistry
from app.modules.processing.repository import ProcessingRepository
from app.modules.processing.runner import ProcessingRunner
from app.storage.local_store import LocalStorage
from tests.fixtures.fake_extractors import FailingExtractor
from tests.fixtures.sample_files import CSV_BYTES

BACKEND_DIR = Path(__file__).resolve().parents[2]
TS = "2026-11-01 10:00:00.000000"


def _cfg(url: str) -> Config:
    # No ini file: keeps logging untouched. env.py reads the URL from attributes.
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["sqlalchemy_url"] = url
    return cfg


@pytest.fixture
def db_url(tmp_path) -> str:
    return f"sqlite+pysqlite:///{(tmp_path / 'proc.db').as_posix()}"


@pytest.fixture
def migrated_engine(db_url):
    command.upgrade(_cfg(db_url), "head")
    engine = build_engine(Settings(DATABASE_URL=db_url))
    yield engine
    engine.dispose()


@pytest.fixture
def sessions(migrated_engine) -> sessionmaker[Session]:
    return sessionmaker(migrated_engine, expire_on_commit=False)


def _seed_evidence(db: Session, storage: LocalStorage | None = None, data: bytes = CSV_BYTES):
    case = Case(title="Persistence", description=None, status="open")
    db.add(case)
    db.flush()
    sha = "a" * 64
    if storage is not None:
        sha, _ = storage.put_stream(io.BytesIO(data))
    ev = Evidence(
        case_id=case.id,
        original_filename="ledger.csv",
        evidence_type="tabular",
        mime_type="text/csv",
        byte_size=len(data),
        sha256=sha,
        storage_path=f"{sha[:2]}/{sha[2:4]}/{sha}",
        processing_status="pending",
    )
    db.add(ev)
    db.commit()
    return case, ev


def _result(n_segments: int = 3) -> ExtractionResult:
    return ExtractionResult(
        extractor="csv",
        extractor_version="1",
        outcome="ok",
        segments=[
            SegmentDraft("table_row", f"row {i}", CsvLocator(row=i + 1, line=i + 1))
            for i in range(n_segments)
        ],
    )


def _claim(repo: ProcessingRepository, ev: Evidence, *, force: bool = False) -> int:
    now = utcnow()
    assert repo.claim(ev.case_id, ev.id, force=force, now=now, stale_cutoff=now)
    return repo.get_evidence(ev.case_id, ev.id).processing_attempts


# --- migrations -------------------------------------------------------------------


def test_upgrade_head_on_empty_database_creates_everything(migrated_engine):
    insp = inspect(migrated_engine)
    assert {"cases", "evidence", "extractions", "extraction_segments"} <= set(
        insp.get_table_names()
    )
    evidence_cols = {c["name"] for c in insp.get_columns("evidence")}
    assert {
        "processing_attempts",
        "processing_started_at",
        "processing_completed_at",
        "processing_error_code",
    } <= evidence_cols
    index_names = {i["name"] for i in insp.get_indexes("extractions")}
    assert {"uq_extractions_current", "ix_extractions_case"} <= index_names
    seg_indexes = {i["name"] for i in insp.get_indexes("extraction_segments")}
    assert {"ix_segments_evidence_page", "ix_segments_case"} <= seg_indexes


def test_existing_stage2_rows_survive_the_migration(db_url):
    cfg = _cfg(db_url)
    command.upgrade(cfg, "0002_create_evidence")
    case_id, evidence_id = uuid.uuid4().hex, uuid.uuid4().hex
    raw = create_engine(db_url)
    with raw.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO cases (id, title, description, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (case_id, "Old case", None, "open", TS, TS),
        )
        conn.exec_driver_sql(
            "INSERT INTO evidence (id, case_id, original_filename, evidence_type, mime_type, "
            "byte_size, sha256, storage_path, processing_status, processing_error, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                evidence_id,
                case_id,
                "old.pdf",
                "document",
                "application/pdf",
                10,
                "b" * 64,
                "bb/bb/" + "b" * 64,
                "pending",
                None,
                TS,
                TS,
            ),
        )

    command.upgrade(cfg, "head")

    with raw.connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT original_filename, processing_status, processing_attempts, "
            "processing_error_code, processing_started_at, processing_completed_at "
            "FROM evidence WHERE id = ?",
            (evidence_id,),
        ).one()
    assert tuple(row) == ("old.pdf", "pending", 0, None, None, None)
    raw.dispose()


def test_downgrade_removes_only_what_stage3_added(db_url):
    cfg = _cfg(db_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0002_create_evidence")
    engine = create_engine(db_url)
    insp = inspect(engine)
    assert "extractions" not in insp.get_table_names()
    assert "extraction_segments" not in insp.get_table_names()
    assert {"cases", "evidence"} <= set(insp.get_table_names())
    cols = {c["name"] for c in insp.get_columns("evidence")}
    assert "processing_attempts" not in cols
    assert {"processing_status", "processing_error"} <= cols  # Stage 2 columns stay
    engine.dispose()


# --- history constraints ----------------------------------------------------------


def test_database_allows_only_one_current_run_per_evidence(sessions):
    with sessions() as db:
        _, ev = _seed_evidence(db)
        for run_number in (1, 2):
            db.add(
                Extraction(
                    evidence_id=ev.id,
                    case_id=ev.case_id,
                    run_number=run_number,
                    run_status="completed",
                    is_current=True,
                    extractor="csv",
                    extractor_version="1",
                    source_sha256=ev.sha256,
                    outcome="ok",
                    doc_metadata={},
                    warnings=[],
                    segment_count=0,
                    duration_ms=0,
                    started_at=utcnow(),
                )
            )
        with pytest.raises(IntegrityError):
            db.commit()


def test_database_rejects_duplicate_run_numbers(sessions):
    with sessions() as db:
        _, ev = _seed_evidence(db)
        for _ in range(2):
            db.add(
                Extraction(
                    evidence_id=ev.id,
                    case_id=ev.case_id,
                    run_number=1,
                    run_status="failed",
                    is_current=False,
                    extractor="csv",
                    extractor_version="1",
                    source_sha256=ev.sha256,
                    doc_metadata={},
                    warnings=[],
                    segment_count=0,
                    duration_ms=0,
                    started_at=utcnow(),
                )
            )
        with pytest.raises(IntegrityError):
            db.commit()


def test_many_failed_runs_may_coexist_with_one_current(sessions):
    with sessions() as db:
        _, ev = _seed_evidence(db)
        repo = ProcessingRepository(db)
        for attempt in (1, 2, 3):
            assert _claim(repo, ev, force=attempt > 1) == attempt
            if attempt == 2:
                repo.record_failure(
                    db.get(Evidence, ev.id),
                    run_number=2,
                    started_at=utcnow(),
                    extractor_name="csv",
                    extractor_version="1",
                    source_sha256=ev.sha256,
                    error_code="corrupt_file",
                    error_message="x",
                    duration_ms=1,
                )
            else:
                repo.record_success(
                    db.get(Evidence, ev.id),
                    run_number=attempt,
                    started_at=utcnow(),
                    result=_result(),
                    source_sha256=ev.sha256,
                    duration_ms=1,
                )
        runs = repo.list_extractions(ev.case_id, ev.id)
        assert [(r.run_number, r.run_status, r.is_current) for r in runs] == [
            (3, "completed", True),
            (2, "failed", False),
            (1, "completed", False),
        ]


# --- transaction atomicity ----------------------------------------------------------


def test_failure_while_saving_segments_changes_nothing(sessions, monkeypatch):
    with sessions() as db:
        _, ev = _seed_evidence(db)
        repo = ProcessingRepository(db)
        _claim(repo, ev)
        first = repo.record_success(
            db.get(Evidence, ev.id),
            run_number=1,
            started_at=utcnow(),
            result=_result(3),
            source_sha256=ev.sha256,
            duration_ms=1,
        )
        first_id = first.id
        _claim(repo, ev, force=True)

        real = repository_module.promoted_columns
        calls = {"n": 0}

        def explode_on_third(locator):
            calls["n"] += 1
            if calls["n"] == 3:
                raise RuntimeError("disk error while saving")
            return real(locator)

        monkeypatch.setattr(repository_module, "promoted_columns", explode_on_third)
        with pytest.raises(RuntimeError):
            repo.record_success(
                db.get(Evidence, ev.id),
                run_number=2,
                started_at=utcnow(),
                result=_result(5),
                source_sha256=ev.sha256,
                duration_ms=1,
            )
        db.rollback()
        monkeypatch.setattr(repository_module, "promoted_columns", real)

        runs = repo.list_extractions(ev.case_id, ev.id)
        assert [(r.run_number, r.is_current) for r in runs] == [(1, True)]
        assert db.scalar(select(func.count()).select_from(ExtractionSegment)) == 3
        assert repo.get_current_extraction(ev.case_id, ev.id).id == first_id


def test_runner_records_failure_when_saving_results_fails(sessions, tmp_path, monkeypatch):
    storage = LocalStorage(tmp_path / "blobs")
    with sessions() as db:
        case, ev = _seed_evidence(db, storage)
        case_id, evidence_id = case.id, ev.id
    registry = ExtractorRegistry()
    registry.register("text/csv", CsvExtractor())
    runner = ProcessingRunner(
        session_factory=sessions,
        storage=storage,
        registry=registry,
        executor=InlineExecutor(),
        settings=Settings(),
    )

    def boom(locator):
        raise RuntimeError("cannot write")

    monkeypatch.setattr(repository_module, "promoted_columns", boom)
    assert runner.run_one(case_id, evidence_id) == "failed"

    with sessions() as db:
        ev = db.get(Evidence, evidence_id)
        assert ev.processing_status == "failed"
        assert ev.processing_error_code == "internal_error"
        assert ev.processing_error == "The extraction result could not be saved."
        assert db.scalar(select(func.count()).select_from(ExtractionSegment)) == 0
        (run,) = db.scalars(select(Extraction)).all()
        assert run.run_status == "failed" and run.is_current is False


def test_runner_failure_isolation_with_real_commits(sessions, tmp_path):
    storage = LocalStorage(tmp_path / "blobs")
    with sessions() as db:
        case, good = _seed_evidence(db, storage)
        bad = Evidence(
            case_id=case.id,
            original_filename="bad.csv",
            evidence_type="tabular",
            mime_type="application/x-bad",
            byte_size=3,
            sha256=good.sha256,
            storage_path="x",
            processing_status="pending",
        )
        db.add(bad)
        db.commit()
        case_id, good_id, bad_id = case.id, good.id, bad.id
    registry = ExtractorRegistry()
    registry.register("text/csv", CsvExtractor())
    registry.register("application/x-bad", FailingExtractor(CorruptFileError("broken")))
    runner = ProcessingRunner(
        session_factory=sessions,
        storage=storage,
        registry=registry,
        executor=InlineExecutor(),
        settings=Settings(),
    )

    runner.run_batch(case_id, [bad_id, good_id])

    with sessions() as db:
        assert db.get(Evidence, bad_id).processing_status == "failed"
        assert db.get(Evidence, good_id).processing_status == "completed"
        assert (
            db.scalar(
                select(func.count())
                .select_from(ExtractionSegment)
                .where(ExtractionSegment.evidence_id == bad_id)
            )
            == 0
        )


# --- concurrency ------------------------------------------------------------------


def test_two_workers_racing_for_one_item_produce_one_run(sessions, tmp_path):
    storage = LocalStorage(tmp_path / "blobs")
    with sessions() as db:
        case, ev = _seed_evidence(db, storage)
        case_id, evidence_id = case.id, ev.id
    registry = ExtractorRegistry()
    registry.register("text/csv", CsvExtractor())

    def make_runner() -> ProcessingRunner:
        return ProcessingRunner(
            session_factory=sessions,
            storage=storage,
            registry=registry,
            executor=InlineExecutor(),
            settings=Settings(),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(lambda r: r.run_one(case_id, evidence_id), [make_runner(), make_runner()])
        )

    assert sorted(outcomes) == ["completed", "skipped"]
    with sessions() as db:
        assert db.get(Evidence, evidence_id).processing_attempts == 1
        assert db.scalar(select(func.count()).select_from(Extraction)) == 1


# --- cascades with real foreign keys --------------------------------------------------


def test_cascade_removes_runs_and_segments(sessions):
    with sessions() as db:
        case, ev = _seed_evidence(db)
        repo = ProcessingRepository(db)
        _claim(repo, ev)
        repo.record_success(
            db.get(Evidence, ev.id),
            run_number=1,
            started_at=utcnow(),
            result=_result(4),
            source_sha256=ev.sha256,
            duration_ms=1,
        )
        assert db.scalar(select(func.count()).select_from(ExtractionSegment)) == 4
        db.delete(db.get(Case, case.id))  # case -> evidence -> extractions -> segments
        db.commit()
        assert db.scalar(select(func.count()).select_from(Evidence)) == 0
        assert db.scalar(select(func.count()).select_from(Extraction)) == 0
        assert db.scalar(select(func.count()).select_from(ExtractionSegment)) == 0
