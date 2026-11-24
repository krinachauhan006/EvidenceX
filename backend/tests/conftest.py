"""Shared pytest fixtures.

Integration tests run against a real database. By default that is an isolated
SQLite file (zero infrastructure, deterministic). Set ``TEST_DATABASE_URL`` to a
Postgres URL to exercise the same suite against Postgres.

Processing tests share ONE session/transaction with the HTTP layer (rolled back
after each test). Background work therefore runs against the same data the test
created. Tests that need real commits and rollbacks (persistence atomicity,
migrations) build their own file-backed database instead; see
``tests/integration/test_processing_persistence.py``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.database import Base, get_db
from app.main import create_app

# Import models so their tables are registered on Base.metadata.
from app.modules.analysis import models as _analysis_models  # noqa: F401
from app.modules.analysis.router import get_analysis_runner, get_analysis_service
from app.modules.analysis.runner import AnalysisRunner, RuleBasedClaimExtractor
from app.modules.analysis.service import AnalysisService
from app.modules.cases import models as _cases_models  # noqa: F401
from app.modules.evidence import models as _evidence_models  # noqa: F401
from app.modules.evidence.router import get_service as get_evidence_service
from app.modules.evidence.service import EvidenceService
from app.modules.processing import models as _processing_models  # noqa: F401
from app.modules.processing.executor import InlineExecutor
from app.modules.processing.registry import ExtractorRegistry, build_default_registry
from app.modules.processing.router import get_processing_service, get_runner
from app.modules.processing.runner import ProcessingRunner
from app.modules.processing.service import ProcessingService
from app.storage.local_store import LocalStorage


@pytest.fixture(scope="session")
def db_engine():
    url = os.environ.get("TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, future=True, connect_args=connect_args)

    # SQLite needs the pragma per connection for FK cascade to apply in tests.
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _fk(dbapi_connection, _record):  # noqa: ANN001
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Iterator[Session]:
    """A session wrapped in a transaction that is rolled back after each test,
    keeping tests isolated from one another."""
    connection = db_engine.connect()
    transaction = connection.begin()
    TestingSession = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def storage(tmp_path) -> LocalStorage:
    """A LocalStorage rooted in a per-test temp directory."""
    return LocalStorage(tmp_path / "storage")


@pytest.fixture
def settings() -> Settings:
    """A fresh Settings object tests may adjust without touching global state."""
    return Settings()


@pytest.fixture
def registry() -> ExtractorRegistry:
    """The default extractor registry. Tests may register fakes on it."""
    return build_default_registry()


@pytest.fixture
def runner(db_session: Session, storage: LocalStorage, registry, settings) -> ProcessingRunner:
    """A runner that reuses the test session instead of opening its own."""

    @contextmanager
    def shared_session() -> Iterator[Session]:
        yield db_session  # not closed here; the db_session fixture owns it

    return ProcessingRunner(
        session_factory=shared_session,
        storage=storage,
        registry=registry,
        executor=InlineExecutor(),
        settings=settings,
    )


@pytest.fixture
def analysis_runner(db_session: Session, settings) -> AnalysisRunner:
    """Case analysis on the test session, always with the offline rule-based extractor."""

    @contextmanager
    def shared_session() -> Iterator[Session]:
        yield db_session

    return AnalysisRunner(
        session_factory=shared_session, settings=settings, extractor=RuleBasedClaimExtractor()
    )


@pytest.fixture
def client(
    db_session: Session, storage: LocalStorage, registry, settings, runner, analysis_runner
) -> Iterator[TestClient]:
    """A TestClient whose dependencies use the test session, temp storage, the
    test registry and the test runner (uploads never touch real storage)."""
    app = create_app()

    def _override_get_db() -> Iterator[Session]:
        yield db_session

    def _override_evidence_service() -> EvidenceService:
        return EvidenceService(db_session, storage=storage)

    def _override_processing_service() -> ProcessingService:
        return ProcessingService(db_session, registry, settings)

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_evidence_service] = _override_evidence_service
    app.dependency_overrides[get_processing_service] = _override_processing_service
    app.dependency_overrides[get_runner] = lambda: runner
    app.dependency_overrides[get_analysis_service] = lambda: AnalysisService(db_session, settings)
    app.dependency_overrides[get_analysis_runner] = lambda: analysis_runner
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
