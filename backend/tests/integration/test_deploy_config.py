"""Deployment configuration: start-up checks (S3, production cookie, Vercel), the
database URL and pool options, and the serverless message for missing engines.

No network, no cloud credentials and no external database are used.
"""

from __future__ import annotations

import logging
import socket

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool, QueuePool, StaticPool

import app.main as main_module
from app.core.config import Settings
from app.core.database import engine_options
from app.core.deploy_checks import (
    ConfigurationError,
    check_deployment_config,
    configuration_problems,
    configuration_warnings,
)
from app.main import create_app
from app.storage import factory
from app.storage.s3_store import S3Storage

SECRET = "never-shown-secret-value-123"
ACCESS = "never-shown-access-key"
PG = "postgresql+psycopg://user:pw@db.example.invalid:5432/evidencex"


@pytest.fixture(autouse=True)
def _clean_storage_cache():
    factory.clear_storage_cache()
    yield
    factory.clear_storage_cache()


def _s3(**extra) -> dict:
    return {
        "STORAGE_BACKEND": "s3",
        "S3_BUCKET": "evidence",
        "S3_ACCESS_KEY_ID": ACCESS,
        "S3_SECRET_ACCESS_KEY": SECRET,
        **extra,
    }


def _vercel_ok(**extra) -> Settings:
    return Settings(
        VERCEL="1",
        APP_ENV="production",
        COOKIE_SECURE=True,
        DATABASE_URL=PG,
        PROCESSING_ISOLATION="inline",
        MAX_UPLOAD_SIZE_MB=4,
        MAX_VIDEO_UPLOAD_MB=4,
        **_s3(**extra),
    )


# --- defaults stay unchanged ------------------------------------------------------------


def test_local_development_defaults_have_no_problems():
    s = Settings()
    assert s.storage_backend == "local" and s.vercel is False
    assert configuration_problems(s) == [] and configuration_warnings(s) == []


def test_a_valid_vercel_configuration_passes():
    assert configuration_problems(_vercel_ok()) == []
    assert configuration_warnings(_vercel_ok()) == []


# --- S3 ---------------------------------------------------------------------------------


@pytest.mark.parametrize("missing", ["S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"])
def test_s3_requires_each_setting_and_names_it_without_values(missing):
    values = _s3()
    values[missing] = ""
    problems = configuration_problems(Settings(**values))
    assert len(problems) == 1 and missing in problems[0]
    assert SECRET not in problems[0] and ACCESS not in problems[0]


def test_whitespace_only_s3_settings_count_as_missing():
    problems = configuration_problems(Settings(**_s3(S3_BUCKET="   ")))
    assert problems and "S3_BUCKET" in problems[0]


def test_an_empty_endpoint_is_allowed_for_aws_s3():
    assert configuration_problems(Settings(**_s3(S3_ENDPOINT_URL=""))) == []


def test_s3_client_is_built_at_startup_without_any_network_request(monkeypatch):
    def no_network(*_a, **_k):  # noqa: ANN002, ANN003
        raise AssertionError("a network connection was attempted")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    s = Settings(**_s3(S3_ENDPOINT_URL="https://ref.storage.supabase.co/storage/v1/s3"))
    check_deployment_config(s)
    assert isinstance(factory.build_storage(s), S3Storage)  # constructed and cached


def test_an_invalid_endpoint_is_reported_by_type_not_value():
    problems = configuration_problems(Settings(**_s3(S3_ENDPOINT_URL="not a url ::")))
    assert problems and "S3 storage client could not be created" in problems[0]
    assert "not a url" not in problems[0]


def test_the_factory_cache_key_is_not_the_plaintext_secret():
    factory.build_storage(Settings(**_s3()))
    assert factory._S3_CACHE
    for key in factory._S3_CACHE:
        assert SECRET not in key and ACCESS not in key and len(key) == 64


def test_rotated_credentials_get_a_new_client():
    a = factory.build_storage(Settings(**_s3()))
    b = factory.build_storage(Settings(**_s3(S3_SECRET_ACCESS_KEY="rotated-secret")))
    assert a is not b


# --- production and Vercel -------------------------------------------------------------


def test_production_requires_a_secure_cookie():
    problems = configuration_problems(Settings(APP_ENV="production"))
    assert any("COOKIE_SECURE" in p for p in problems)
    assert configuration_problems(Settings(APP_ENV="production", COOKIE_SECURE=True)) == []


@pytest.mark.parametrize(
    ("override", "name"),
    [
        ({"DATABASE_URL": "sqlite+pysqlite:///./var/evidencex.db"}, "DATABASE_URL"),
        ({"STORAGE_BACKEND": "local"}, "STORAGE_BACKEND"),
        ({"PROCESSING_ISOLATION": "subprocess"}, "PROCESSING_ISOLATION"),
    ],
)
def test_vercel_refuses_unsafe_state_and_subprocesses(override, name):
    values = {
        "VERCEL": "1",
        "APP_ENV": "production",
        "COOKIE_SECURE": True,
        "DATABASE_URL": PG,
        "PROCESSING_ISOLATION": "inline",
        **_s3(),
        **override,
    }
    problems = configuration_problems(Settings(**values))
    assert len(problems) == 1 and name in problems[0], problems


def test_vercel_warns_when_upload_limits_exceed_the_platform_limit(caplog):
    s = _vercel_ok()
    s = s.model_copy(update={"max_upload_size_mb": 25, "max_video_upload_mb": 200})
    warnings = configuration_warnings(s)
    assert len(warnings) == 2 and "MAX_UPLOAD_SIZE_MB=25" in warnings[0]
    with caplog.at_level(logging.WARNING):
        check_deployment_config(s)  # a warning, not a refusal
    assert "4.5 MB" in caplog.text


def test_all_problems_are_reported_together():
    with pytest.raises(ConfigurationError) as info:
        check_deployment_config(Settings(VERCEL="1", APP_ENV="production"))
    names = " ".join(info.value.problems)
    for name in ("COOKIE_SECURE", "DATABASE_URL", "STORAGE_BACKEND", "PROCESSING_ISOLATION"):
        assert name in names


def test_the_app_refuses_to_start_with_an_invalid_configuration(monkeypatch):
    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(main_module, "engine", eng)
    app = create_app(Settings(**_s3(S3_BUCKET="")))
    with pytest.raises(ConfigurationError, match="S3_BUCKET"):
        with TestClient(app):
            pass
    eng.dispose()


def test_docker_production_defaults_still_start_up():
    # backend/Dockerfile: APP_ENV=production, COOKIE_SECURE=true, SQLite + local storage
    # on the /data volume, subprocess isolation; not on Vercel.
    s = Settings(
        APP_ENV="production",
        COOKIE_SECURE=True,
        DATABASE_URL="sqlite+pysqlite:////data/evidencex.db",
        STORAGE_ROOT="/data/storage",
    )
    assert configuration_problems(s) == []


# --- database URL and pool -------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgres://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"),
        (
            "postgresql://u:p@h:6543/d?sslmode=require",
            "postgresql+psycopg://u:p@h:6543/d?sslmode=require",
        ),
        ("postgresql+psycopg://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
        ("  postgresql://u@h/d  ", "postgresql+psycopg://u@h/d"),
        ("sqlite+pysqlite:///./var/evidencex.db", "sqlite+pysqlite:///./var/evidencex.db"),
    ],
)
def test_provider_postgres_urls_use_the_installed_psycopg_driver(given, expected):
    assert Settings(DATABASE_URL=given).database_url == expected


def test_sqlite_engine_options_are_unchanged():
    assert engine_options(Settings()) == {"connect_args": {"check_same_thread": False}}


def test_postgres_uses_a_small_checked_pool():
    opts = engine_options(Settings(DATABASE_URL=PG))
    assert opts == {"pool_pre_ping": True, "pool_size": 2, "max_overflow": 3, "pool_recycle": 300}
    eng = create_engine(PG, **opts)  # no connection is opened by create_engine
    assert isinstance(eng.pool, QueuePool) and eng.pool._pre_ping
    eng.dispose()


def test_transaction_pooler_disables_client_pool_and_prepared_statements():
    opts = engine_options(Settings(DATABASE_URL=PG, DATABASE_TRANSACTION_POOLER=True))
    assert opts["poolclass"] is NullPool
    assert opts["connect_args"] == {"prepare_threshold": None}
    assert opts["pool_pre_ping"] is True
    assert "pool_size" not in opts


def test_database_secrets_are_not_in_settings_repr():
    assert "pw@" not in repr(Settings(DATABASE_URL=PG).model_dump(exclude={"database_url"}))


# --- processing on a serverless deployment ---------------------------------------------


def test_missing_engine_on_vercel_explains_the_deployment_limit(
    db_session, storage, registry, settings
):
    from contextlib import contextmanager

    from app.modules.cases.models import Case
    from app.modules.evidence.service import EvidenceService
    from app.modules.processing.errors import DependencyMissingError
    from app.modules.processing.executor import InlineExecutor
    from app.modules.processing.runner import SERVERLESS_ENGINE_MESSAGE, ProcessingRunner

    class NoEngine:
        name, version = "csv", "test"

        def extract(self, _inp):  # noqa: ANN001, ANN201
            raise DependencyMissingError("Tesseract OCR was not found. Install it ...")

    registry.register("text/csv", NoEngine())
    case = Case(title="serverless")
    db_session.add(case)
    db_session.commit()

    import io

    ev = EvidenceService(db_session, storage=storage, settings=settings).upload(
        case.id, filename="a.csv", fileobj=io.BytesIO(b"id,v\n1,2\n")
    )

    @contextmanager
    def shared():
        yield db_session

    vercel = settings.model_copy(update={"vercel": True})
    ProcessingRunner(
        session_factory=shared,
        storage=storage,
        registry=registry,
        executor=InlineExecutor(),
        settings=vercel,
    ).run_one(case.id, ev.id)
    db_session.refresh(ev)
    assert ev.processing_status == "failed"
    assert ev.processing_error_code == "dependency_missing"
    assert ev.processing_error == SERVERLESS_ENGINE_MESSAGE
    assert "Install" not in ev.processing_error


# --- migration scripts found when the app package is pip-installed ---------------------


def test_migration_scripts_are_found_from_the_working_directory(tmp_path, monkeypatch):
    from app.core import schema

    backend = schema.BACKEND_DIR
    monkeypatch.setattr(schema, "BACKEND_DIR", tmp_path / "site-packages")  # no alembic here
    monkeypatch.chdir(backend)  # the deployment's project root
    schema.expected_revision.cache_clear()
    try:
        assert schema.migrations_dir() == backend
        assert schema.expected_revision() and schema.expected_revision().startswith("0007")
    finally:
        schema.expected_revision.cache_clear()


def test_production_refuses_clearly_when_migration_scripts_are_missing(tmp_path, monkeypatch):
    from app.core import schema
    from app.main import SchemaNotReadyError, check_schema_for_production

    monkeypatch.setattr(schema, "BACKEND_DIR", tmp_path / "a")
    monkeypatch.chdir(tmp_path)
    schema.expected_revision.cache_clear()
    eng = create_engine("sqlite+pysqlite:///:memory:")
    try:
        assert schema.migrations_dir() is None
        with pytest.raises(SchemaNotReadyError, match="migration scripts"):
            check_schema_for_production(
                Settings(APP_ENV="production", COOKIE_SECURE=True), db_engine=eng
            )
    finally:
        eng.dispose()
        schema.expected_revision.cache_clear()
