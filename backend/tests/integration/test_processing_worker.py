"""The local multimodal processing worker (app/worker.py, ``python -m app.cli worker``).

Each test uses its own database with real commits and separate connections (claims,
heartbeat, concurrent analysis), temporary local storage or a fake S3 client, and
fake engines, so no Tesseract, speech model or network is needed.

Database: a SQLite FILE per test by default. When ``TEST_DATABASE_URL`` is a
PostgreSQL URL, every test runs on PostgreSQL instead, in its own throwaway schema
(created and dropped by the test) so it never touches other tables. That URL must be
the LOCAL scratch server (loopback address, port 55432): anything else fails the
test instead of connecting, and a supplied URL never silently falls back to SQLite.
Nothing here touches a real deployment.
"""

from __future__ import annotations

import io
import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import Base, build_engine
from app.core.db_types import as_utc, utcnow
from app.core.exceptions import ConflictError
from app.modules.analysis.models import AnalysisRun, Claim
from app.modules.analysis.repository import AnalysisRepository
from app.modules.analysis.runner import AnalysisRunner, RuleBasedClaimExtractor
from app.modules.analysis.service import AnalysisService
from app.modules.cases.schemas import CaseCreate
from app.modules.cases.service import CaseService
from app.modules.evidence.models import Evidence
from app.modules.evidence.service import EvidenceService
from app.modules.processing.errors import (
    CorruptFileError,
    DependencyMissingError,
    ExtractionInterruptedError,
    ExtractionTimeoutError,
)
from app.modules.processing.executor import InlineExecutor
from app.modules.processing.extractors.base import (
    ExtractionResult,
    ExtractionWarning,
    SegmentDraft,
)
from app.modules.processing.locators import ImageLocator
from app.modules.processing.models import Extraction, ExtractionSegment
from app.modules.processing.registry import ExtractorRegistry
from app.modules.processing.repository import ProcessingRepository
from app.modules.processing.runner import ProcessingRunner
from app.storage import factory, s3_store
from app.storage.local_store import LocalStorage
from app.worker import (
    DEFAULT_WORKER_MIMES,
    Heartbeat,
    PassReport,
    ProcessingWorker,
    WorkerLock,
    WorkerLockError,
    cases_needing_analysis,
    describe_pass,
    find_candidates,
    install_stop_handlers,
    needs_ocr_rerun,
    ocr_available,
    worker_mime_types,
)
from tests.fixtures.fake_extractors import FailingExtractor, FakeOcrExtractor
from tests.fixtures.sample_files import CSV_BYTES, PDF_BYTES, PNG_BYTES, WAV_BYTES, WEBM_BYTES
from tests.unit.test_s3_storage import FakeS3


class NeedsOcrPdf:
    """What the serverless deployment produces for a scanned PDF: no text, OCR missing."""

    name = "pymupdf"
    version = "test"

    def __init__(self, outcome: str = "needs_ocr", ocr_unavailable: bool = True) -> None:
        self.outcome = outcome
        self.ocr_unavailable = ocr_unavailable

    def extract(self, inp):  # noqa: ANN001, ANN201
        warnings = [ExtractionWarning("pages_need_ocr", "no text layer", {"pages": [1]})]
        if self.ocr_unavailable:
            warnings.insert(0, ExtractionWarning("ocr_unavailable", "Tesseract was not found."))
        return ExtractionResult(self.name, self.version, self.outcome, [], {}, warnings)


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
SCRATCH_PG_PORT = 55432


def scratch_postgres_url() -> str | None:
    """The PostgreSQL URL to test against, or None for SQLite. Fails (never connects)
    when TEST_DATABASE_URL is set to anything but the local scratch server."""
    raw = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not raw or raw.startswith("sqlite"):
        return None
    try:
        url = make_url(raw)
    except Exception:  # noqa: BLE001 - never echo the URL (it may hold a password)
        pytest.fail("TEST_DATABASE_URL is not a valid database URL")
    if not url.drivername.startswith("postgresql"):
        pytest.fail("TEST_DATABASE_URL must be SQLite or the local scratch PostgreSQL")
    if url.host not in LOOPBACK_HOSTS or url.port != SCRATCH_PG_PORT:
        pytest.fail(
            "Refusing TEST_DATABASE_URL: worker tests only run against a PostgreSQL "
            f"server on a loopback address, port {SCRATCH_PG_PORT} (the local scratch "
            "database). Nothing was connected to."
        )
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


@contextmanager
def postgres_schema_engine(url: str) -> Iterator[Engine]:
    """An engine whose connections use a fresh, private schema on the scratch server."""
    schema = f"evx_worker_{uuid.uuid4().hex[:12]}"
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    eng = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema}", "application_name": schema},
    )
    try:
        Base.metadata.create_all(eng)
        yield eng
    finally:
        eng.dispose()
        with admin.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


@contextmanager
def worker_engine(tmp_path) -> Iterator[Engine]:  # noqa: ANN001
    pg_url = scratch_postgres_url()
    if pg_url is not None:
        with postgres_schema_engine(pg_url) as eng:
            yield eng
        return
    eng = build_engine(
        Settings(DATABASE_URL=f"sqlite+pysqlite:///{(tmp_path / 'worker.db').as_posix()}")
    )
    try:
        Base.metadata.create_all(eng)
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def env(tmp_path):
    with worker_engine(tmp_path) as eng:
        yield from _env(eng, tmp_path)


def _env(eng, tmp_path):  # noqa: ANN001, ANN202
    factory_ = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    settings = Settings(
        STORAGE_ROOT=str(tmp_path / "storage"),
        PROCESSING_ISOLATION="inline",
        PROCESSING_STALE_MINUTES=10,
        WHISPER_MODEL_DIR=str(tmp_path / "no-models"),
    )
    storage = LocalStorage(tmp_path / "storage")
    yield eng, factory_, settings, storage, tmp_path


def new_case(factory_, title="Case") -> object:
    with factory_() as db:
        return CaseService(db).create(CaseCreate(title=title, description=None)).id


def upload(factory_, settings, storage, case_id, name, data) -> object:
    with factory_() as db:
        return (
            EvidenceService(db, settings=settings, storage=storage)
            .upload(case_id, filename=name, fileobj=io.BytesIO(data))
            .id
        )


def evidence(factory_, evidence_id) -> Evidence:
    with factory_() as db:
        return db.get(Evidence, evidence_id)


def set_state(factory_, evidence_id, **values) -> None:
    with factory_() as db:
        ev = db.get(Evidence, evidence_id)
        for k, v in values.items():
            setattr(ev, k, v)
        db.commit()


def runs(factory_, evidence_id) -> list[Extraction]:
    with factory_() as db:
        return list(
            db.scalars(
                select(Extraction)
                .where(Extraction.evidence_id == evidence_id)
                .order_by(Extraction.run_number)
            )
        )


def worker_registry(**by_mime) -> ExtractorRegistry:
    reg = ExtractorRegistry()
    fake = FakeOcrExtractor()
    for mime in (*DEFAULT_WORKER_MIMES, "application/pdf"):
        reg.register(mime, fake)
    for mime, extractor in by_mime.items():
        reg.register(mime.replace("_", "/", 1), extractor)
    return reg


def make_worker(env, registry=None, **kw) -> ProcessingWorker:
    _, factory_, settings, storage, _ = env
    kw.setdefault("ocr_check", lambda: True)
    kw.setdefault(
        "analysis_runner",
        AnalysisRunner(
            session_factory=factory_, settings=settings, extractor=RuleBasedClaimExtractor()
        ),
    )
    return ProcessingWorker(
        session_factory=factory_,
        settings=settings,
        storage=kw.pop("storage", storage),
        registry=registry or worker_registry(),
        executor=InlineExecutor(),
        **kw,
    )


def serverless_runner(env, registry) -> ProcessingRunner:
    """The API server's runner: same code, an engine-less registry."""
    _, factory_, settings, storage, _ = env
    return ProcessingRunner(
        session_factory=factory_,
        storage=storage,
        registry=registry,
        executor=InlineExecutor(),
        settings=settings,
    )


# --- configuration ------------------------------------------------------------------


def test_worker_types_default_to_ocr_speech_and_video_and_follow_the_setting():
    assert {"image/png", "audio/wav", "video/mp4"} <= worker_mime_types(Settings())
    assert "application/pdf" not in worker_mime_types(Settings())
    assert worker_mime_types(Settings(EXTERNAL_WORKER_MIMES="audio/wav")) == {"audio/wav"}


@pytest.mark.parametrize(
    ("outcome", "codes", "expected"),
    [
        ("needs_ocr", ["ocr_unavailable", "pages_need_ocr"], True),
        ("partial", ["ocr_unavailable", "pages_need_ocr"], True),
        ("partial", ["ocr_unavailable"], False),
        ("needs_ocr", ["pages_need_ocr"], False),  # OCR ran there; a re-run would not help
        ("partial", ["pages_need_ocr", "ocr_failed"], False),
        ("ok", ["ocr_unavailable"], False),
    ],
)
def test_needs_ocr_rerun(outcome, codes, expected):
    assert needs_ocr_rerun(outcome, [{"code": c, "message": ""} for c in codes]) is expected


# --- discovery -------------------------------------------------------------------------


def test_discovers_pending_failed_and_stale_multimodal_evidence(env):
    _, factory_, settings, storage, _ = env
    case_id = new_case(factory_)
    pend_png = upload(factory_, settings, storage, case_id, "a.png", PNG_BYTES)
    pend_wav = upload(factory_, settings, storage, case_id, "b.wav", WAV_BYTES)
    upload(factory_, settings, storage, case_id, "c.csv", CSV_BYTES)  # not a worker type
    dep = upload(factory_, settings, storage, case_id, "d.png", PNG_BYTES + b"d")
    corrupt = upload(factory_, settings, storage, case_id, "e.png", PNG_BYTES + b"e")
    stale = upload(factory_, settings, storage, case_id, "f.png", PNG_BYTES + b"f")
    busy = upload(factory_, settings, storage, case_id, "g.png", PNG_BYTES + b"g")
    done = upload(factory_, settings, storage, case_id, "h.png", PNG_BYTES + b"h")
    set_state(factory_, dep, processing_status="failed", processing_error_code="dependency_missing")
    set_state(factory_, corrupt, processing_status="failed", processing_error_code="corrupt_file")
    set_state(
        factory_,
        stale,
        processing_status="processing",
        processing_started_at=utcnow() - timedelta(minutes=30),
    )
    set_state(factory_, busy, processing_status="processing", processing_started_at=utcnow())
    set_state(factory_, done, processing_status="completed")

    found = {c.evidence_id: c.reason for c in find_candidates(factory_, settings)}
    assert found == {
        pend_png: "pending",
        pend_wav: "pending",
        dep: "dependency_missing",
        stale: "stale",
    }
    wider = {
        c.evidence_id: c.reason for c in find_candidates(factory_, settings, retry_failed=True)
    }
    assert wider[corrupt] == "failed" and busy not in wider and done not in wider


def test_dry_run_discovery_issues_no_write_statements(env):
    eng, factory_, settings, storage, _ = env
    case_id = new_case(factory_)
    upload(factory_, settings, storage, case_id, "a.png", PNG_BYTES)
    statements: list[str] = []

    def record(_conn, _cursor, statement, *_args):  # noqa: ANN001
        statements.append(statement.strip().split()[0].upper())

    event.listen(eng, "before_cursor_execute", record)
    try:
        assert len(find_candidates(factory_, settings)) == 1
    finally:
        event.remove(eng, "before_cursor_execute", record)
    assert statements and set(statements) <= {"SELECT"}


# --- recovery and persistence -------------------------------------------------------------


def test_recovers_evidence_the_serverless_server_failed_and_persists_the_run(env):
    _, factory_, settings, storage, _ = env
    case_id = new_case(factory_)
    ev_id = upload(factory_, settings, storage, case_id, "gate.png", PNG_BYTES)
    # The deployment tried first and had no OCR engine.
    serverless = ExtractorRegistry()
    serverless.register("image/png", FailingExtractor(DependencyMissingError("no tesseract")))
    assert serverless_runner(env, serverless).run_one(case_id, ev_id) == "failed"
    assert evidence(factory_, ev_id).processing_error_code == "dependency_missing"

    report = make_worker(env).run_pass()
    assert [(c.reason, s) for c, s in report.results] == [("dependency_missing", "completed")]
    ev = evidence(factory_, ev_id)
    assert (ev.processing_status, ev.processing_error_code, ev.processing_attempts) == (
        "completed",
        None,
        2,
    )
    first, second = runs(factory_, ev_id)
    assert (first.run_status, first.is_current) == ("failed", False)
    assert (second.run_status, second.is_current, second.extractor) == (
        "completed",
        True,
        "fake-ocr",
    )
    with factory_() as db:
        seg = db.scalar(
            select(ExtractionSegment).where(ExtractionSegment.extraction_id == second.id)
        )
    assert seg.segment_type == "ocr_line" and "10:34" in seg.text
    assert seg.locator["kind"] == "image"
    # Nothing left to do on the next pass.
    assert make_worker(env).run_pass().candidates == 0


def test_reads_the_file_from_the_s3_bucket(env, monkeypatch):
    _, factory_, settings, _, _ = env
    fake = FakeS3()
    monkeypatch.setattr(s3_store, "_build_client", lambda **_: fake)
    factory.clear_storage_cache()
    s3 = settings.model_copy(
        update={
            "storage_backend": "s3",
            "s3_bucket": "evidence",
            "s3_access_key_id": "id",
            "s3_secret_access_key": __import__("pydantic").SecretStr("secret"),
        }
    )
    try:
        bucket = factory.build_storage(s3)
        case_id = new_case(factory_)
        ev_id = upload(factory_, s3, bucket, case_id, "gate.png", PNG_BYTES)
        report = make_worker(env, storage=bucket).run_pass()
    finally:
        factory.clear_storage_cache()
    assert report.count("completed") == 1
    assert evidence(factory_, ev_id).processing_status == "completed"
    assert any(op == "get_object" for op, _ in fake.calls)


def test_scanned_pdf_is_rerun_once_when_ocr_was_unavailable(env):
    _, factory_, settings, storage, _ = env
    case_id = new_case(factory_)
    scanned = upload(factory_, settings, storage, case_id, "scan.pdf", PDF_BYTES)
    ocr_failed = upload(factory_, settings, storage, case_id, "hard.pdf", PDF_BYTES + b"%2")
    text_pdf = upload(factory_, settings, storage, case_id, "text.pdf", PDF_BYTES + b"%3")
    for ev_id, extractor in (
        (scanned, NeedsOcrPdf()),
        (ocr_failed, NeedsOcrPdf(outcome="partial", ocr_unavailable=False)),
        (text_pdf, FakeOcrExtractor()),
    ):
        reg = ExtractorRegistry()
        reg.register("application/pdf", extractor)
        assert serverless_runner(env, reg).run_one(case_id, ev_id) == "completed"

    # Without OCR on this computer the PDF is not taken (it would come out the same).
    assert make_worker(env, ocr_check=lambda: False).candidates() == []
    cands = make_worker(env).candidates()
    assert [(c.evidence_id, c.reason, c.force) for c in cands] == [(scanned, "scanned_pdf", True)]

    worker = make_worker(env)
    report = worker.run_pass()
    assert report.count("completed") == 1
    old, new = runs(factory_, scanned)
    assert (old.outcome, old.is_current) == ("needs_ocr", False)  # history kept
    assert (new.outcome, new.is_current, new.run_number) == ("ok", True, 2)
    # The new current run has no OCR gap: not selected again, no duplicate runs.
    assert worker.run_pass().candidates == 0
    assert make_worker(env).run_pass().candidates == 0
    assert len(runs(factory_, scanned)) == 2 and len(runs(factory_, ocr_failed)) == 1


# --- claiming --------------------------------------------------------------------------------


def test_competing_claims_have_exactly_one_winner(env):
    _, factory_, settings, storage, _ = env
    case_id = new_case(factory_)
    ev_id = upload(factory_, settings, storage, case_id, "gate.png", PNG_BYTES)
    now = utcnow()
    cutoff = now - timedelta(minutes=10)
    wins = []
    barrier = threading.Barrier(4)

    def claim() -> None:
        with factory_() as db:
            barrier.wait()
            wins.append(
                ProcessingRepository(db).claim(
                    case_id, ev_id, force=False, now=now, stale_cutoff=cutoff
                )
            )

    threads = [threading.Thread(target=claim) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(wins) == [False, False, False, True]
    assert evidence(factory_, ev_id).processing_attempts == 1


def test_item_claimed_elsewhere_after_discovery_is_skipped(env):
    _, factory_, settings, storage, _ = env
    case_id = new_case(factory_)
    ev_id = upload(factory_, settings, storage, case_id, "gate.png", PNG_BYTES)
    fake = FakeOcrExtractor()
    worker = make_worker(env, registry=worker_registry(image_png=fake))
    (cand,) = worker.candidates()
    with factory_() as db:  # the API server (or another worker) wins the claim first
        assert ProcessingRepository(db).claim(
            case_id, ev_id, force=False, now=utcnow(), stale_cutoff=utcnow() - timedelta(minutes=10)
        )
    assert worker.process(cand) == "skipped"
    assert fake.calls == 0 and runs(factory_, ev_id) == []


# --- heartbeat ----------------------------------------------------------------------------------


def test_heartbeat_keeps_a_long_item_fresh_and_stops_with_it(env):
    _, factory_, settings, storage, _ = env
    case_id = new_case(factory_)
    ev_id = upload(factory_, settings, storage, case_id, "call.wav", WAV_BYTES)
    started, release = threading.Event(), threading.Event()
    fake = FakeOcrExtractor(started=started, release=release)
    worker = make_worker(env, registry=worker_registry(audio_wav=fake), heartbeat_seconds=0.05)
    (cand,) = worker.candidates()
    result: list[str] = []
    t = threading.Thread(target=lambda: result.append(worker.process(cand)))
    t.start()
    assert started.wait(10)
    first = as_utc(evidence(factory_, ev_id).processing_started_at)
    deadline = time.monotonic() + 10
    while as_utc(evidence(factory_, ev_id).processing_started_at) <= first:
        assert time.monotonic() < deadline, "the heartbeat never refreshed the claim"
        time.sleep(0.02)
    release.set()
    t.join(10)
    assert result == ["completed"]
    after = evidence(factory_, ev_id)
    stamp = after.processing_started_at
    time.sleep(0.2)  # the heartbeat stopped with the item
    assert evidence(factory_, ev_id).processing_started_at == stamp
    assert after.processing_status == "completed"


def test_heartbeat_never_touches_an_item_it_no_longer_owns(env):
    _, factory_, settings, storage, _ = env
    case_id = new_case(factory_)
    ev_id = upload(factory_, settings, storage, case_id, "gate.png", PNG_BYTES)
    old = utcnow() - timedelta(minutes=5)
    set_state(
        factory_,
        ev_id,
        processing_status="processing",
        processing_attempts=1,
        processing_started_at=old,
    )
    assert Heartbeat(factory_, ev_id, 1, 60).beat() is True
    refreshed = as_utc(evidence(factory_, ev_id).processing_started_at)
    assert refreshed > as_utc(old)
    # Reclaimed by someone else (attempts went up): this claim's heartbeat is refused.
    set_state(factory_, ev_id, processing_attempts=2, processing_started_at=old)
    hb = Heartbeat(factory_, ev_id, 1, 60)
    assert hb.beat() is False and hb.lost
    assert as_utc(evidence(factory_, ev_id).processing_started_at) == as_utc(old)
    # Finished items are never touched either.
    set_state(factory_, ev_id, processing_status="completed", processing_attempts=1)
    assert Heartbeat(factory_, ev_id, 1, 60).beat() is False


# --- failure isolation ---------------------------------------------------------------


def test_one_failing_item_does_not_stop_the_others_and_is_not_retried_in_a_loop(env, monkeypatch):
    _, factory_, settings, storage, _ = env
    case_id = new_case(factory_)
    bad = upload(factory_, settings, storage, case_id, "bad.png", PNG_BYTES)
    missing = upload(factory_, settings, storage, case_id, "nomodel.webm", WEBM_BYTES)
    crash = upload(factory_, settings, storage, case_id, "crash.png", PNG_BYTES + b"c")
    good = upload(factory_, settings, storage, case_id, "call.wav", WAV_BYTES)
    reg = worker_registry(
        image_png=FailingExtractor(CorruptFileError("unreadable")),
        video_webm=FailingExtractor(DependencyMissingError("PyAV is not installed")),
    )
    worker = make_worker(env, registry=reg)
    real = worker._runner.run_one

    def run_one(case_id_, evidence_id, *a, **k):  # noqa: ANN002, ANN003, ANN202
        if evidence_id == crash:
            raise RuntimeError("runner crashed")
        return real(case_id_, evidence_id, *a, **k)

    monkeypatch.setattr(worker._runner, "run_one", run_one)
    report = worker.run_pass()
    statuses = {c.evidence_id: s for c, s in report.results}
    assert statuses == {bad: "failed", missing: "failed", crash: "error", good: "completed"}
    assert evidence(factory_, good).processing_status == "completed"
    assert evidence(factory_, bad).processing_error_code == "corrupt_file"
    # The worker's own dependency_missing failure is not retried by the same process
    # (no loop of failed runs); the crashed item is left for the next pass.
    again = worker.run_pass()
    assert {c.evidence_id for c, _ in again.results} == {crash}
    assert len(runs(factory_, missing)) == 1


# --- shutdown ------------------------------------------------------------------------


def test_stop_request_finishes_the_current_item_then_stops(env):
    _, factory_, settings, storage, _ = env
    case_id = new_case(factory_)
    ids = [
        upload(factory_, settings, storage, case_id, f"{i}.png", PNG_BYTES + bytes([i]))
        for i in range(3)
    ]
    stop = threading.Event()

    class StopsDuringExtraction(FakeOcrExtractor):
        def extract(self, inp):  # noqa: ANN001, ANN201
            stop.set()  # Ctrl+C pressed while the first item is being extracted
            return super().extract(inp)

    worker = make_worker(
        env, registry=worker_registry(image_png=StopsDuringExtraction()), stop=stop
    )
    report = worker.run_pass()
    assert report.interrupted is True
    assert [s for _, s in report.results] == ["completed"]  # finished, not abandoned
    assert [evidence(factory_, i).processing_status for i in ids] == [
        "completed",
        "pending",
        "pending",
    ]
    # Analysis is deferred, not lost, when stopping.
    assert report.analysis == {}
    assert worker.run_forever(poll_seconds=0) == 0  # already stopped: returns at once


def test_run_forever_polls_until_stopped(env):
    _, factory_, settings, storage, _ = env
    case_id = new_case(factory_)
    upload(factory_, settings, storage, case_id, "a.png", PNG_BYTES)
    stop = threading.Event()
    worker = make_worker(env, stop=stop)
    passes = []
    real = worker.run_pass

    def counting():  # noqa: ANN202
        passes.append(1)
        if len(passes) == 3:
            stop.set()
        return real()

    worker.run_pass = counting  # type: ignore[method-assign]
    assert worker.run_forever(poll_seconds=0.01) == 3


def test_first_ctrl_c_requests_a_graceful_stop_and_the_second_interrupts():
    import signal

    stop = threading.Event()
    messages: list[str] = []
    before = signal.getsignal(signal.SIGINT)
    restore = install_stop_handlers(stop, messages.append)
    try:
        handler = signal.getsignal(signal.SIGINT)
        handler(signal.SIGINT, None)
        assert stop.is_set() and "finishing the current item" in messages[0]
        with pytest.raises(KeyboardInterrupt):
            handler(signal.SIGINT, None)
    finally:
        restore()
    assert signal.getsignal(signal.SIGINT) is before


# --- lock ----------------------------------------------------------------------------


def test_only_one_worker_can_hold_the_lock(tmp_path):
    path = tmp_path / "worker.lock"
    first = WorkerLock(path)
    first.acquire()
    try:
        with pytest.raises(WorkerLockError, match="already running"):
            WorkerLock(path).acquire()
    finally:
        first.release()
    with WorkerLock(path):  # released: a new worker may start
        pass


def test_cli_refuses_to_start_while_another_worker_holds_the_lock(env, monkeypatch, capsys):
    import app.cli as cli
    from app.core import config as config_module

    _, factory_, settings, _, tmp_path = env
    monkeypatch.setattr(cli, "SessionLocal", factory_)
    monkeypatch.setattr(config_module, "get_settings", lambda: settings)
    path = tmp_path / "w.lock"
    with WorkerLock(path):
        assert cli.main(["worker", "--once", "--lock-file", str(path)]) == 2
    assert "already running" in capsys.readouterr().err


def test_cli_refuses_postgres_with_local_storage(monkeypatch, capsys):
    import app.cli as cli
    from app.core import config as config_module

    pg = Settings(DATABASE_URL="postgresql://user:pw@db.example.invalid:5432/x")
    monkeypatch.setattr(config_module, "get_settings", lambda: pg)
    assert cli.main(["worker", "--once"]) == 2
    err = capsys.readouterr().err
    assert "STORAGE_BACKEND is local" in err and "pw" not in err


def test_cli_dry_run_lists_candidates_and_changes_nothing(env, monkeypatch, capsys):
    import app.cli as cli
    from app.core import config as config_module

    _, factory_, settings, storage, tmp_path = env
    case_id = new_case(factory_)
    ev_id = upload(factory_, settings, storage, case_id, "gate.png", PNG_BYTES)
    monkeypatch.setattr(cli, "SessionLocal", factory_)
    monkeypatch.setattr(config_module, "get_settings", lambda: settings)

    def snapshot() -> list[tuple]:
        with factory_() as db:
            rows = db.execute(
                select(
                    Evidence.id,
                    Evidence.processing_status,
                    Evidence.processing_attempts,
                    Evidence.processing_started_at,
                    Evidence.updated_at,
                )
            ).all()
            counts = tuple(
                db.scalar(select(func.count()).select_from(m))
                for m in (Extraction, ExtractionSegment, AnalysisRun, Claim)
            )
        return [*rows, counts]

    before = snapshot()
    lock = tmp_path / "never.lock"
    assert cli.main(["worker", "--dry-run", "--lock-file", str(lock)]) == 0
    out = capsys.readouterr().out
    assert "1 eligible item(s)" in out and "gate.png" in out and "pending" in out
    assert "nothing was claimed or changed" in out
    assert snapshot() == before
    assert evidence(factory_, ev_id).processing_attempts == 0
    assert not lock.exists()  # a dry run does not even take the lock


# --- analysis ------------------------------------------------------------------------


def test_cases_are_analysed_once_after_successful_processing(env):
    _, factory_, settings, storage, _ = env
    done_case = new_case(factory_, "Processed")
    failed_case = new_case(factory_, "Only failures")
    upload(factory_, settings, storage, done_case, "a.png", PNG_BYTES)
    upload(factory_, settings, storage, done_case, "b.wav", WAV_BYTES)
    upload(factory_, settings, storage, failed_case, "bad.webm", WEBM_BYTES)
    reg = worker_registry(video_webm=FailingExtractor(CorruptFileError("bad")))
    report = make_worker(env, registry=reg).run_pass()
    assert report.analysis == {done_case: "completed"}  # one run, not one per item
    with factory_() as db:
        run_rows = list(db.scalars(select(AnalysisRun)))
        claims = db.scalar(
            select(func.count()).select_from(Claim).where(Claim.case_id == done_case)
        )
    assert [(r.case_id, r.status) for r in run_rows] == [(done_case, "completed")]
    assert claims > 0


def test_active_analysis_is_not_duplicated_and_is_retried_next_pass(env):
    _, factory_, settings, storage, _ = env
    case_id = new_case(factory_)
    upload(factory_, settings, storage, case_id, "a.png", PNG_BYTES)
    with factory_() as db:  # someone started an analysis of this case
        busy = AnalysisRun(case_id=case_id, status="running", method="rule_based_v1", stats={})
        db.add(busy)
        db.commit()
        busy_id = busy.id
    worker = make_worker(env)
    first = worker.run_pass()
    assert first.analysis == {case_id: "conflict"}
    with factory_() as db:
        assert db.scalar(select(func.count()).select_from(AnalysisRun)) == 1
        db.get(AnalysisRun, busy_id).status = "completed"
        db.commit()
    second = worker.run_pass()
    assert second.candidates == 0 and second.analysis == {case_id: "completed"}
    with factory_() as db:
        assert db.scalar(select(func.count()).select_from(AnalysisRun)) == 2


def test_analysis_can_be_turned_off(env):
    _, factory_, settings, storage, _ = env
    case_id = new_case(factory_)
    upload(factory_, settings, storage, case_id, "a.png", PNG_BYTES)
    report = make_worker(env, analyse=False).run_pass()
    assert report.count("completed") == 1 and report.analysis == {}
    with factory_() as db:
        assert db.scalar(select(func.count()).select_from(AnalysisRun)) == 0


# --- hardening: helpers ------------------------------------------------------------


def one_line_result() -> ExtractionResult:
    return ExtractionResult(
        "fake-ocr",
        "1",
        "ok",
        [SegmentDraft("ocr_line", "line", ImageLocator(bbox=[0, 0, 1, 1], width=2, height=2))],
    )


def claim(factory_, case_id, ev_id, *, force=False, stale=False) -> int:  # noqa: ANN001
    """Claim like a runner does. ``stale=True`` treats every running claim as
    abandoned, i.e. another worker reclaiming it. Returns the new attempt number."""
    now = utcnow()
    cutoff = now + timedelta(minutes=1) if stale else now - timedelta(minutes=10)
    with factory_() as db:
        repo = ProcessingRepository(db)
        assert repo.claim(case_id, ev_id, force=force, now=now, stale_cutoff=cutoff)
        return repo.get_evidence(case_id, ev_id).processing_attempts


def save_success(factory_, ev_id, run_number) -> bool:  # noqa: ANN001
    with factory_() as db:
        ev = db.get(Evidence, ev_id)
        saved = ProcessingRepository(db).record_success(
            ev,
            run_number=run_number,
            started_at=utcnow(),
            result=one_line_result(),
            source_sha256=ev.sha256,
            duration_ms=1,
        )
    return saved is not None


def save_failure(factory_, ev_id, run_number) -> bool:  # noqa: ANN001
    with factory_() as db:
        ev = db.get(Evidence, ev_id)
        saved = ProcessingRepository(db).record_failure(
            ev,
            run_number=run_number,
            started_at=utcnow(),
            extractor_name="fake-ocr",
            extractor_version="1",
            source_sha256=ev.sha256,
            error_code="corrupt_file",
            error_message="unreadable",
            duration_ms=1,
        )
    return saved is not None


def scanned_pdf(env) -> tuple[object, object]:  # noqa: ANN001
    """A scanned PDF the serverless deployment completed without OCR."""
    _, factory_, settings, storage, _ = env
    case_id = new_case(factory_)
    ev_id = upload(factory_, settings, storage, case_id, "scan.pdf", PDF_BYTES)
    reg = ExtractorRegistry()
    reg.register("application/pdf", NeedsOcrPdf())
    assert serverless_runner(env, reg).run_one(case_id, ev_id) == "completed"
    return case_id, ev_id


class NoBlobs:
    """Storage whose files are all missing (deleted object, wrong bucket)."""

    def exists(self, content_hash: str) -> bool:
        return False

    def open(self, content_hash: str):  # noqa: ANN201
        raise FileNotFoundError(content_hash)


# --- A1: an unsuccessful scanned-PDF re-run is never repeated ---------------------------


def test_ocr_counts_as_available_only_with_the_configured_language_data(monkeypatch):
    from app.modules.processing.extractors import ocr_engine, ocr_languages

    monkeypatch.setattr(ocr_engine.TesseractEngine, "version", lambda self, options: "t 5")
    monkeypatch.setattr(ocr_languages, "installed_languages", lambda cmd="": ["eng", "osd"])
    assert ocr_available(Settings(TESSERACT_LANGS="eng")) is True
    # Tesseract runs, but the Hindi data is missing: every page would fail again.
    assert ocr_available(Settings(TESSERACT_LANGS="eng+hin")) is False
    monkeypatch.setattr(ocr_languages, "installed_languages", lambda cmd="": None)
    assert ocr_available(Settings(TESSERACT_LANGS="eng")) is False


def test_an_ocr_rerun_that_still_cannot_read_the_pages_is_never_repeated(env):
    _, factory_, _, _, _ = env
    _, scanned = scanned_pdf(env)
    # Here, too, OCR cannot read the pages (for example language data missing).
    reg = worker_registry(application_pdf=NeedsOcrPdf())
    worker = make_worker(env, registry=reg)
    first = worker.run_pass()
    assert [(c.reason, s) for c, s in first.results] == [("scanned_pdf", "completed")]
    for _ in range(3):  # successive polling passes
        assert worker.run_pass().candidates == 0
    # A restarted worker does not try again either: the history shows the retry.
    assert make_worker(env, registry=reg).candidates() == []
    assert len(runs(factory_, scanned)) == 2


# --- B3: completed scanned PDFs are protected ---------------------------------------------


def test_scanned_pdf_is_not_selected_without_a_local_pdf_extractor(env):
    _, factory_, settings, _, _ = env
    scanned_pdf(env)
    no_pdf = ExtractorRegistry()
    for mime in DEFAULT_WORKER_MIMES:
        no_pdf.register(mime, FakeOcrExtractor())
    assert make_worker(env, registry=no_pdf).candidates() == []
    assert find_candidates(factory_, settings, pdf_supported=False, ocr_check=lambda: True) == []
    assert len(find_candidates(factory_, settings, ocr_check=lambda: True)) == 1


@pytest.mark.parametrize("failure", ["storage_missing", "timeout"])
def test_a_failed_ocr_rerun_keeps_the_pdf_completed_with_its_previous_run(env, failure):
    _, factory_, _, _, _ = env
    _, scanned = scanned_pdf(env)
    (first,) = runs(factory_, scanned)
    if failure == "storage_missing":
        worker = make_worker(env, storage=NoBlobs())
    else:
        slow = FailingExtractor(ExtractionTimeoutError("OCR took too long and was stopped."))
        worker = make_worker(env, registry=worker_registry(application_pdf=slow))
    report = worker.run_pass()
    assert [s for _, s in report.results] == ["failed"]
    ev = evidence(factory_, scanned)
    assert (ev.processing_status, ev.processing_error_code, ev.processing_error) == (
        "completed",
        None,
        None,
    )
    old, new = runs(factory_, scanned)
    assert (old.id, old.is_current) == (first.id, True)  # still what the UI shows
    assert (new.run_status, new.error_code, new.is_current) == ("failed", failure, False)
    assert worker.run_pass().candidates == 0
    assert make_worker(env).candidates() == []  # not retried after a restart either


def test_an_interrupted_ocr_rerun_keeps_the_pdf_completed_and_is_retried_later(env):
    _, factory_, _, _, _ = env
    _, scanned = scanned_pdf(env)
    stopped = FailingExtractor(ExtractionInterruptedError("OCR was interrupted."))
    worker = make_worker(env, registry=worker_registry(application_pdf=stopped))
    assert [s for _, s in worker.run_pass().results] == ["failed"]
    assert evidence(factory_, scanned).processing_status == "completed"
    assert worker.run_pass().candidates == 0  # not again in the same process
    restarted = make_worker(env)  # an interruption says nothing about the file
    assert [(c.reason, s) for c, s in restarted.run_pass().results] == [
        ("scanned_pdf", "completed")
    ]
    current = [r for r in runs(factory_, scanned) if r.is_current]
    assert [(r.outcome, r.run_number) for r in current] == [("ok", 3)]


# --- B2: an interrupted OCR run is recoverable -------------------------------------------


def test_an_interrupted_image_is_retried_automatically_by_the_next_worker_run(env):
    _, factory_, settings, storage, _ = env
    case_id = new_case(factory_)
    ev_id = upload(factory_, settings, storage, case_id, "gate.png", PNG_BYTES)
    stopped = FailingExtractor(ExtractionInterruptedError("OCR was interrupted."))
    worker = make_worker(env, registry=worker_registry(image_png=stopped))
    assert [s for _, s in worker.run_pass().results] == ["failed"]
    ev = evidence(factory_, ev_id)
    assert (ev.processing_status, ev.processing_error_code) == ("failed", "interrupted")
    assert worker.run_pass().candidates == 0  # the stopping process does not loop
    restarted = make_worker(env)
    (cand,) = restarted.candidates()
    assert cand.reason == "interrupted"
    assert [s for _, s in restarted.run_pass().results] == ["completed"]
    assert evidence(factory_, ev_id).processing_status == "completed"


# --- B1: saving is conditional on still owning the claim --------------------------------


def test_a_stale_attempt_cannot_save_over_a_newer_claim(env):
    _, factory_, settings, storage, _ = env
    case_id = new_case(factory_)
    ev_id = upload(factory_, settings, storage, case_id, "gate.png", PNG_BYTES)
    assert claim(factory_, case_id, ev_id) == 1
    assert claim(factory_, case_id, ev_id, stale=True) == 2  # another worker took over
    assert save_success(factory_, ev_id, 1) is False
    assert save_failure(factory_, ev_id, 1) is False
    ev = evidence(factory_, ev_id)
    assert (ev.processing_status, ev.processing_attempts, ev.processing_error_code) == (
        "processing",
        2,
        None,
    )
    assert runs(factory_, ev_id) == []
    assert save_success(factory_, ev_id, 2) is True  # the owner still can
    assert evidence(factory_, ev_id).processing_status == "completed"


def test_a_stale_failing_attempt_leaves_the_previous_success_current(env):
    _, factory_, settings, storage, _ = env
    case_id = new_case(factory_)
    ev_id = upload(factory_, settings, storage, case_id, "gate.png", PNG_BYTES)
    assert claim(factory_, case_id, ev_id) == 1
    assert save_success(factory_, ev_id, 1) is True
    assert claim(factory_, case_id, ev_id, force=True) == 2  # a re-run starts
    assert claim(factory_, case_id, ev_id, stale=True) == 3  # and is reclaimed
    assert save_failure(factory_, ev_id, 2) is False
    assert save_success(factory_, ev_id, 2) is False
    assert [(r.run_number, r.is_current) for r in runs(factory_, ev_id)] == [(1, True)]
    ev = evidence(factory_, ev_id)
    assert (ev.processing_status, ev.processing_attempts) == ("processing", 3)
    assert save_success(factory_, ev_id, 3) is True
    assert [(r.run_number, r.is_current) for r in runs(factory_, ev_id)] == [
        (1, False),
        (3, True),
    ]


class ReclaimedDuringExtraction(FakeOcrExtractor):
    """While this attempt extracts, another worker reclaims the item as stale."""

    def __init__(self, factory_, case_id, ev_id, *, fail: bool = False) -> None:  # noqa: ANN001
        super().__init__()
        self.factory_, self.case_id, self.ev_id, self.fail = factory_, case_id, ev_id, fail

    def extract(self, inp):  # noqa: ANN001, ANN201
        claim(self.factory_, self.case_id, self.ev_id, stale=True)
        if self.fail:
            raise CorruptFileError("unreadable")
        return super().extract(inp)


@pytest.mark.parametrize("fail", [False, True])
def test_the_runner_discards_its_result_when_a_newer_attempt_took_over(env, fail):
    _, factory_, settings, storage, _ = env
    case_id = new_case(factory_)
    ev_id = upload(factory_, settings, storage, case_id, "gate.png", PNG_BYTES)
    ext = ReclaimedDuringExtraction(factory_, case_id, ev_id, fail=fail)
    report = make_worker(env, registry=worker_registry(image_png=ext)).run_pass()
    assert [s for _, s in report.results] == ["superseded"]
    ev = evidence(factory_, ev_id)
    # The newer attempt still owns the item: not completed by us, not marked failed.
    assert (ev.processing_status, ev.processing_attempts, ev.processing_error_code) == (
        "processing",
        2,
        None,
    )
    assert runs(factory_, ev_id) == []


def test_a_stale_claim_is_recovered_and_completed_by_the_worker(env):
    _, factory_, settings, storage, _ = env
    case_id = new_case(factory_)
    ev_id = upload(factory_, settings, storage, case_id, "gate.png", PNG_BYTES)
    set_state(
        factory_,
        ev_id,
        processing_status="processing",
        processing_attempts=1,
        processing_started_at=utcnow() - timedelta(minutes=30),
    )
    report = make_worker(env).run_pass()
    assert [(c.reason, s) for c, s in report.results] == [("stale", "completed")]
    ev = evidence(factory_, ev_id)
    assert (ev.processing_status, ev.processing_attempts) == ("completed", 2)
    assert [r.run_number for r in runs(factory_, ev_id)] == [2]


# --- B7: no transaction is held during extraction ------------------------------------------


def test_no_database_connection_or_transaction_is_held_during_extraction(env):
    eng, factory_, settings, storage, _ = env
    case_id = new_case(factory_)
    upload(factory_, settings, storage, case_id, "call.wav", WAV_BYTES)
    started, release = threading.Event(), threading.Event()
    fake = FakeOcrExtractor(started=started, release=release)
    worker = make_worker(env, registry=worker_registry(audio_wav=fake), heartbeat_seconds=60)
    (cand,) = worker.candidates()
    result: list[str] = []
    t = threading.Thread(target=lambda: result.append(worker.process(cand)))
    t.start()
    try:
        assert started.wait(10)
        # The claim session is closed: no pooled connection is in use while the
        # (here: deliberately stalled) extractor runs.
        assert eng.pool.checkedout() == 0
        if eng.dialect.name == "postgresql":
            with eng.connect() as conn:
                idle_in_tx = conn.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE application_name = current_setting('application_name') "
                        "AND pid <> pg_backend_pid() AND state LIKE 'idle in transaction%'"
                    )
                ).scalar()
            assert idle_in_tx == 0
    finally:
        release.set()
        t.join(10)
    assert result == ["completed"]


# --- B4: concurrent analysis starts -------------------------------------------------------


def test_concurrent_analysis_starts_create_exactly_one_running_run(env, monkeypatch):
    _, factory_, settings, _, _ = env
    case_id = new_case(factory_)
    real = AnalysisRepository.active_run

    def slow_active_run(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        found = real(self, *args, **kwargs)
        time.sleep(0.3)  # widen the gap between the check and the insert
        return found

    monkeypatch.setattr(AnalysisRepository, "active_run", slow_active_run)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def start() -> None:
        with factory_() as db:
            barrier.wait()
            try:
                AnalysisService(db, settings).start_run(case_id, "rule_based_v1")
                outcomes.append("started")
            except ConflictError:
                outcomes.append("conflict")

    threads = [threading.Thread(target=start) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(outcomes) == ["conflict", "started"]
    with factory_() as db:
        running = db.scalar(
            select(func.count()).select_from(AnalysisRun).where(AnalysisRun.status == "running")
        )
    assert running == 1


# --- B6: analysis is rediscovered, not only remembered -------------------------------------


def test_a_worker_restarted_between_processing_and_analysis_analyses_the_case(env):
    _, factory_, settings, storage, _ = env
    case_id = new_case(factory_)
    upload(factory_, settings, storage, case_id, "gate.png", PNG_BYTES)
    # Another case processed by the deployment itself (CSV) is not the worker's business.
    other = new_case(factory_, "Spreadsheet only")
    csv_id = upload(factory_, settings, storage, other, "ledger.csv", CSV_BYTES)
    from app.modules.processing.extractors.csv_extractor import CsvExtractor

    csv_reg = ExtractorRegistry()
    csv_reg.register("text/csv", CsvExtractor())
    assert serverless_runner(env, csv_reg).run_one(other, csv_id) == "completed"

    first = make_worker(env, analyse=False).run_pass()  # stopped before analysing
    assert first.count("completed") == 1 and first.analysis == {}
    assert cases_needing_analysis(factory_, settings) == {case_id}

    second = make_worker(env).run_pass()  # the next start catches up
    assert second.candidates == 0 and second.analysis == {case_id: "completed"}
    assert make_worker(env).run_pass().analysis == {}  # and does not repeat it
    assert cases_needing_analysis(factory_, settings) == set()


def test_the_once_summary_does_not_claim_a_busy_case_is_retried():
    report = PassReport(analysis={"case": "conflict"})
    assert "retried next pass" in describe_pass(report)
    once = describe_pass(report, continuous=False)
    assert "not retried by --once" in once and "retried next pass" not in once
