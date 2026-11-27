"""Seeding the fictional Missing Shipment demo case (app/demo_seed.py, app.cli seed-demo).

Each test uses its own SQLite file and a temporary storage folder (or a fake S3
client). The demo files are read from the repository and never modified. Expected
outcomes are asserted only where they do not depend on optional engines: Tesseract
and the speech model may or may not be installed on the machine running the tests.
"""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import Base, build_engine
from app.demo_seed import DEMO_DIR, DEMO_FILES, DEMO_TITLE, SeedError, seed_demo_case
from app.modules.auth.models import CaseMember, User
from app.modules.auth.schemas import RegisterRequest
from app.modules.auth.service import AuthService
from app.modules.cases.models import Case
from app.modules.evidence.models import Evidence
from app.storage import factory, s3_store
from app.storage.local_store import LocalStorage
from app.storage.s3_store import S3Storage
from tests.unit.test_s3_storage import FakeS3

OWNER = "demo.owner@example.org"
JUDGE = "judge@example.org"


@pytest.fixture
def env(tmp_path):
    # The application's engine builder: foreign keys (ON DELETE CASCADE) enforced.
    eng = build_engine(
        Settings(DATABASE_URL=f"sqlite+pysqlite:///{(tmp_path / 'seed.db').as_posix()}")
    )
    Base.metadata.create_all(eng)
    factory_ = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    settings = Settings(
        STORAGE_ROOT=str(tmp_path / "storage"),
        PROCESSING_ISOLATION="inline",
        WHISPER_MODEL_DIR=str(tmp_path / "no-models"),
    )
    with factory_() as db:
        for email in (OWNER, JUDGE):
            AuthService(db, settings).register(
                RegisterRequest(
                    email=email, display_name=email.split("@")[0], password="a long demo password"
                )
            )
    yield factory_, settings, tmp_path
    eng.dispose()


def _count(factory_, model) -> int:  # noqa: ANN001
    with factory_() as db:
        return int(db.scalar(select(func.count()).select_from(model)) or 0)


def test_demo_files_are_present_and_fictional():
    assert all((DEMO_DIR / name).is_file() for name in DEMO_FILES)
    assert "fictional" in (DEMO_DIR / "README.md").read_text("utf-8").lower()


def test_dry_run_changes_nothing(env):
    factory_, settings, _ = env
    result = seed_demo_case(
        session_factory=factory_,
        settings=settings,
        owner_email=OWNER,
        viewer_emails=[JUDGE],
        dry_run=True,
    )
    assert result.status == "dry-run" and set(result.files) == set(DEMO_FILES)
    assert _count(factory_, Case) == 0 and _count(factory_, Evidence) == 0


@pytest.mark.parametrize("viewers", [[], ["nobody@example.org"]])
def test_unknown_accounts_are_refused_before_anything_is_written(env, viewers):
    factory_, settings, _ = env
    owner = "missing@example.org" if not viewers else OWNER
    with pytest.raises(SeedError, match="register"):
        seed_demo_case(
            session_factory=factory_, settings=settings, owner_email=owner, viewer_emails=viewers
        )
    assert _count(factory_, Case) == 0


def test_missing_demo_files_are_refused(env, tmp_path):
    factory_, settings, _ = env
    with pytest.raises(SeedError, match="demo files not found"):
        seed_demo_case(
            session_factory=factory_,
            settings=settings,
            owner_email=OWNER,
            demo_dir=tmp_path / "empty",
        )
    assert _count(factory_, Case) == 0


def test_seed_creates_processes_and_analyses_the_case_once(env):
    factory_, settings, tmp_path = env
    result = seed_demo_case(
        session_factory=factory_, settings=settings, owner_email=OWNER, viewer_emails=[JUDGE]
    )
    assert result.status == "created" and set(result.files) == set(DEMO_FILES)
    # Text formats need no optional engine and must be extracted.
    for name in ("delivery_receipt.pdf", "pallet_ledger.csv", "witness_email.eml"):
        assert result.files[name] == "completed", (name, result.errors)
    # Nothing is left half-done: every file either completed or failed with a code.
    for name, status in result.files.items():
        assert status in ("completed", "failed"), name
        assert status == "completed" or result.errors.get(name), name
    assert result.analysis["claims"] > 0

    with factory_() as db:
        case = db.get(Case, result.case_id)
        assert case.title == DEMO_TITLE and "fictional" in (case.description or "").lower()
        roles = dict(
            db.execute(
                select(User.email, CaseMember.role)
                .join(CaseMember, CaseMember.user_id == User.id)
                .where(CaseMember.case_id == case.id)
            ).all()
        )
        assert roles == {OWNER: "owner", JUDGE: "viewer"}
        rows = list(db.scalars(select(Evidence).where(Evidence.case_id == case.id)))
    storage = LocalStorage(settings.storage_root)
    for ev in rows:
        data = (DEMO_DIR / ev.original_filename).read_bytes()
        assert ev.sha256 == hashlib.sha256(data).hexdigest()
        assert storage.exists(ev.sha256)  # stored under its content hash

    again = seed_demo_case(session_factory=factory_, settings=settings, owner_email=OWNER)
    assert again.status == "exists" and again.case_id == result.case_id
    assert _count(factory_, Case) == 1 and _count(factory_, Evidence) == len(DEMO_FILES)


def test_seed_writes_to_the_configured_s3_bucket(env, monkeypatch):
    factory_, settings, _ = env
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
        result = seed_demo_case(session_factory=factory_, settings=s3, owner_email=OWNER)
    finally:
        factory.clear_storage_cache()
    assert result.status == "created"
    with factory_() as db:
        hashes = set(db.scalars(select(Evidence.sha256).where(Evidence.case_id == result.case_id)))
    assert {("evidence", S3Storage.key_for(h)) for h in hashes} <= set(fake.objects)
    # Processing read the files back from the bucket.
    assert result.files["pallet_ledger.csv"] == "completed"
    assert any(op == "get_object" for op, _ in fake.calls)


def test_cli_requires_confirmation_before_writing(capsys):
    from app.cli import main

    assert main(["seed-demo", "--owner", OWNER]) == 2
    assert "--yes" in capsys.readouterr().err


@pytest.mark.parametrize("fail_at", ["dock_camera.mp4", "viewer"])
def test_a_failed_seed_is_rolled_back_and_can_be_run_again(env, monkeypatch, fail_at):
    from app.modules.auth.service import AuthService as Auth
    from app.modules.evidence.service import EvidenceService

    factory_, settings, _ = env
    storage = LocalStorage(settings.storage_root)
    real_upload, real_add = EvidenceService.upload, Auth.add_member

    def upload(self, case_id, *, filename, fileobj):  # noqa: ANN001, ANN202
        if filename == fail_at:
            raise OSError("simulated storage failure")
        return real_upload(self, case_id, filename=filename, fileobj=fileobj)

    def add_member(self, *a, **k):  # noqa: ANN002, ANN003, ANN202
        if fail_at == "viewer":
            raise RuntimeError("simulated failure")
        return real_add(self, *a, **k)

    monkeypatch.setattr(EvidenceService, "upload", upload)
    monkeypatch.setattr(Auth, "add_member", add_member)
    with pytest.raises(SeedError, match="partially created case and its stored files were removed"):
        seed_demo_case(
            session_factory=factory_,
            settings=settings,
            owner_email=OWNER,
            viewer_emails=[JUDGE],
            process=False,
        )
    # Nothing is left behind: no case, no evidence rows, no memberships, no blobs.
    assert _count(factory_, Case) == 0 and _count(factory_, Evidence) == 0
    assert _count(factory_, CaseMember) == 0
    for name in DEMO_FILES:
        sha = hashlib.sha256((DEMO_DIR / name).read_bytes()).hexdigest()
        assert not storage.exists(sha), name

    monkeypatch.undo()
    again = seed_demo_case(
        session_factory=factory_,
        settings=settings,
        owner_email=OWNER,
        viewer_emails=[JUDGE],
        process=False,
    )
    assert again.status == "created" and _count(factory_, Evidence) == len(DEMO_FILES)


def test_cli_dry_run_writes_nothing_and_needs_no_confirmation(capsys, monkeypatch):
    import app.cli as cli
    from app.demo_seed import SeedResult

    calls = []

    def fake_seed(**kwargs):  # noqa: ANN003, ANN202
        calls.append(kwargs)
        return SeedResult(status="dry-run", files={n: "would upload" for n in DEMO_FILES})

    monkeypatch.setattr("app.demo_seed.seed_demo_case", fake_seed)
    assert cli.main(["seed-demo", "--owner", OWNER, "--dry-run"]) == 0
    assert calls and calls[0]["dry_run"] is True
    assert "Dry run: nothing changed" in capsys.readouterr().out
