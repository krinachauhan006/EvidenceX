"""Failure -> retry -> recovery with REAL commits on a throwaway file database.

The shared-session API tests run inside one outer transaction, which could hide a
missing commit or a rollback problem. These tests use a SQLite file created by Alembic
inside pytest's temporary directory, the production engine settings (WAL, foreign
keys), separate sessions for each step, and a brand-new engine in the middle of the
sequence to simulate a server restart.

The database and storage are created under ``tmp_path`` and nothing else. The live
database and live storage are never opened.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.core.config import Settings
from app.core.database import build_engine
from app.modules.cases.models import Case
from app.modules.evidence.models import Evidence
from app.modules.processing.executor import InlineExecutor
from app.modules.processing.extractors.csv_extractor import CsvExtractor
from app.modules.processing.models import Extraction, ExtractionSegment
from app.modules.processing.registry import ExtractorRegistry
from app.modules.processing.runner import ProcessingRunner
from app.storage.local_store import LocalStorage
from tests.fixtures.blob_control import BACKEND_DIR, hidden_blob
from tests.fixtures.processing_api import unique_csv

BACKEND_ALEMBIC = BACKEND_DIR / "alembic"
MISSING_MESSAGE = "The stored file is missing."
CORRUPT_UTF16_MESSAGE = "The file declares UTF-16 but could not be decoded."


# --- throwaway database --------------------------------------------------------------


@pytest.fixture
def make_sessions(tmp_path):
    """Create the schema with Alembic on a temp file; return a factory that builds
    a NEW engine and session factory each call (a call = a server restart)."""
    db_file = (tmp_path / "recovery.db").resolve()
    # Hard stop: never migrate or open anything inside the backend directory.
    assert BACKEND_DIR.resolve() not in db_file.parents
    url = f"sqlite+pysqlite:///{db_file.as_posix()}"

    cfg = Config()  # no ini file, so logging is left alone
    cfg.set_main_option("script_location", str(BACKEND_ALEMBIC))
    cfg.attributes["sqlalchemy_url"] = url
    command.upgrade(cfg, "head")

    engines = []

    def factory() -> sessionmaker[Session]:
        engine = build_engine(Settings(DATABASE_URL=url))
        engines.append(engine)
        return sessionmaker(engine, expire_on_commit=False)

    yield factory
    for engine in engines:
        engine.dispose()


def build_runner(sessions, storage: LocalStorage) -> ProcessingRunner:
    registry = ExtractorRegistry()
    registry.register("text/csv", CsvExtractor())
    return ProcessingRunner(
        session_factory=sessions,
        storage=storage,
        registry=registry,
        executor=InlineExecutor(),
        settings=Settings(),
    )


def seed(sessions, storage: LocalStorage, data: bytes) -> tuple[uuid.UUID, uuid.UUID, str]:
    """Insert a case and one pending CSV evidence row with its blob (real commit)."""
    sha, size = storage.put_stream(io.BytesIO(data))
    with sessions() as db:
        case = Case(title="Recovery", description=None, status="open")
        db.add(case)
        db.flush()
        evidence = Evidence(
            case_id=case.id,
            original_filename="ledger.csv",
            evidence_type="tabular",
            mime_type="text/csv",
            byte_size=size,
            sha256=sha,
            storage_path=f"{sha[:2]}/{sha[2:4]}/{sha}",
            processing_status="pending",
        )
        db.add(evidence)
        db.commit()
        return case.id, evidence.id, sha


def state(sessions, evidence_id: uuid.UUID) -> dict:
    with sessions() as db:
        evidence = db.get(Evidence, evidence_id)
        runs = db.scalars(
            select(Extraction)
            .where(Extraction.evidence_id == evidence_id)
            .order_by(Extraction.run_number)
        ).all()
        return {
            "status": evidence.processing_status,
            "code": evidence.processing_error_code,
            "error": evidence.processing_error,
            "attempts": evidence.processing_attempts,
            "runs": [
                (r.run_number, r.run_status, r.is_current, r.segment_count, r.error_code)
                for r in runs
            ],
            "run_ids": {r.run_number: r.id for r in runs},
        }


def segment_rows(sessions, extraction_id: uuid.UUID) -> list[tuple]:
    with sessions() as db:
        rows = db.scalars(
            select(ExtractionSegment)
            .where(ExtractionSegment.extraction_id == extraction_id)
            .order_by(ExtractionSegment.seq)
        ).all()
        return [(r.id, r.seq, r.segment_type, r.text, r.data, r.locator) for r in rows]


def total_segment_rows(sessions) -> int:
    with sessions() as db:
        return db.scalar(select(func.count()).select_from(ExtractionSegment)) or 0


# --- the recovery sequence ---------------------------------------------------------------


def test_recovery_sequence_survives_real_commits_and_a_restart(make_sessions, tmp_path):
    storage = LocalStorage(tmp_path / "blobs")
    sessions = make_sessions()
    case_id, eid, sha = seed(sessions, storage, unique_csv(3))
    runner = build_runner(sessions, storage)

    # Run 1 succeeds and is committed.
    assert runner.run_one(case_id, eid) == "completed"
    s1 = state(sessions, eid)
    assert (s1["status"], s1["attempts"]) == ("completed", 1)
    assert s1["runs"] == [(1, "completed", True, 4, None)]
    run1_id = s1["run_ids"][1]
    run1_rows = segment_rows(sessions, run1_id)
    assert len(run1_rows) == 4

    # Run 2: a forced re-run while the file is unavailable.
    with hidden_blob(storage, sha):
        assert runner.run_one(case_id, eid, force=True) == "failed"

    # Simulate a server restart: a brand-new engine and sessions on the same file.
    sessions = make_sessions()
    runner = build_runner(sessions, storage)

    s2 = state(sessions, eid)
    assert (s2["status"], s2["code"], s2["error"], s2["attempts"]) == (
        "failed",
        "storage_missing",
        MISSING_MESSAGE,
        2,
    )
    assert s2["runs"] == [
        (1, "completed", True, 4, None),
        (2, "failed", False, 0, "storage_missing"),
    ]
    assert segment_rows(sessions, run1_id) == run1_rows  # Run 1 untouched
    assert total_segment_rows(sessions) == 4  # the failed run wrote nothing

    # Retry (not forced): the item is failed, so the claim accepts it.
    assert runner.run_one(case_id, eid) == "completed"

    s3 = state(sessions, eid)
    assert (s3["status"], s3["code"], s3["error"], s3["attempts"]) == ("completed", None, None, 3)
    assert s3["runs"] == [
        (1, "completed", False, 4, None),
        (2, "failed", False, 0, "storage_missing"),
        (3, "completed", True, 4, None),
    ]
    assert segment_rows(sessions, run1_id) == run1_rows  # still byte-identical
    run3_rows = segment_rows(sessions, s3["run_ids"][3])
    assert [r[1:] for r in run3_rows] == [r[1:] for r in run1_rows]  # same content
    assert {r[0] for r in run3_rows}.isdisjoint({r[0] for r in run1_rows})  # new rows
    assert total_segment_rows(sessions) == 8


def test_corrupt_file_fails_and_retry_fails_again_with_real_commits(make_sessions, tmp_path):
    storage = LocalStorage(tmp_path / "blobs")
    sessions = make_sessions()
    # Stored directly (bypassing upload validation) so the real extractor decides.
    case_id, eid, _ = seed(sessions, storage, b"\xff\xfe\x61\x00\x62")
    runner = build_runner(sessions, storage)

    assert runner.run_one(case_id, eid) == "failed"
    s1 = state(sessions, eid)
    assert (s1["status"], s1["code"], s1["error"], s1["attempts"]) == (
        "failed",
        "corrupt_file",
        CORRUPT_UTF16_MESSAGE,
        1,
    )
    assert s1["runs"] == [(1, "failed", False, 0, "corrupt_file")]

    # Restart, then retry: still a bad file, so it fails again as a new attempt.
    sessions = make_sessions()
    runner = build_runner(sessions, storage)
    assert runner.run_one(case_id, eid) == "failed"

    s2 = state(sessions, eid)
    assert s2["attempts"] == 2 and s2["status"] == "failed"
    assert s2["runs"] == [
        (1, "failed", False, 0, "corrupt_file"),
        (2, "failed", False, 0, "corrupt_file"),
    ]
    assert total_segment_rows(sessions) == 0


def test_a_failed_first_attempt_recovers_with_real_commits(make_sessions, tmp_path):
    storage = LocalStorage(tmp_path / "blobs")
    sessions = make_sessions()
    case_id, eid, sha = seed(sessions, storage, unique_csv(2))
    runner = build_runner(sessions, storage)

    with hidden_blob(storage, sha):
        assert runner.run_one(case_id, eid) == "failed"
    s1 = state(sessions, eid)
    assert s1["runs"] == [(1, "failed", False, 0, "storage_missing")]
    assert total_segment_rows(sessions) == 0

    assert runner.run_one(case_id, eid) == "completed"
    s2 = state(sessions, eid)
    assert (s2["status"], s2["attempts"], s2["code"], s2["error"]) == ("completed", 2, None, None)
    assert s2["runs"] == [
        (1, "failed", False, 0, "storage_missing"),
        (2, "completed", True, 3, None),
    ]
    assert total_segment_rows(sessions) == 3

    # A completed item is not eligible without force: the runner skips it.
    assert runner.run_one(case_id, eid) == "skipped"
    assert state(sessions, eid)["attempts"] == 2


def test_the_helper_cannot_leave_a_blob_hidden_after_the_test(make_sessions, tmp_path):
    """If a hidden-blob block ever raised, the blob must still come back."""
    storage = LocalStorage(tmp_path / "blobs")
    sessions = make_sessions()
    case_id, eid, sha = seed(sessions, storage, unique_csv(2))
    runner = build_runner(sessions, storage)

    with pytest.raises(RuntimeError, match="interrupted"), hidden_blob(storage, sha):
        assert runner.run_one(case_id, eid) == "failed"
        raise RuntimeError("interrupted")

    assert storage.exists(sha) is True
    assert not Path(storage.path_for(sha)).with_name(sha + ".hold").exists()
    assert runner.run_one(case_id, eid) == "completed"
