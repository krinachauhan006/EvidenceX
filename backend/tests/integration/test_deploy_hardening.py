"""Deployment hardening: API security headers, the production start-up schema guard,
and the reverse-proxy / container contracts that the Docker stack relies on.

Every database here is a throwaway (in-memory or under ``tmp_path``). Nothing touches
``var/evidencex.db``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

import app.main as main_module
from alembic import command
from app.core.config import Settings
from app.main import SchemaNotReadyError, check_schema_for_production, create_app
from tests.integration.test_migration_schema import _cfg, _url

REPO = Path(__file__).resolve().parents[3]
API_CSP = "default-src 'none'; frame-ancestors 'none'"


# --- API response headers -----------------------------------------------------------


def test_api_responses_forbid_scripts_framing_and_caching(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.headers["content-security-policy"] == API_CSP
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_errors_and_refused_requests_carry_the_same_headers(client):
    missing = client.get("/api/cases/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404
    assert missing.headers["content-security-policy"] == API_CSP
    assert missing.headers["cache-control"] == "no-store"
    csrf = client.post(
        "/api/cases", json={"title": "x"}, headers={"Origin": "https://evil.example"}
    )
    assert csrf.status_code == 403
    assert csrf.headers["content-security-policy"] == API_CSP
    assert csrf.headers["cache-control"] == "no-store"


def test_unauthenticated_api_responses_are_not_cacheable(client):
    anon = TestClient(client.app)
    r = anon.get("/api/cases")
    assert r.status_code == 401
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-security-policy"] == API_CSP


def test_health_gets_the_csp_but_interactive_docs_are_left_working(client):
    health = client.get("/health")
    assert health.headers["content-security-policy"] == API_CSP
    for path in ("/docs", "/openapi.json"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "content-security-policy" not in r.headers, path


# --- production start-up guard -------------------------------------------------------


def _memory_engine():
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _production() -> Settings:
    # A valid production configuration (HTTPS cookie), so these tests reach the schema
    # check; the configuration checks themselves are tested in test_deploy_config.py.
    return Settings(APP_ENV="production", COOKIE_SECURE=True)


def test_production_refuses_a_database_without_alembic_revision():
    eng = _memory_engine()
    with eng.begin() as c:
        c.execute(text("CREATE TABLE cases (id TEXT PRIMARY KEY)"))
    try:
        with pytest.raises(SchemaNotReadyError, match="alembic upgrade head"):
            check_schema_for_production(_production(), db_engine=eng)
    finally:
        eng.dispose()


def test_production_refuses_a_database_behind_the_code(tmp_path):
    url = _url(tmp_path / "behind.sqlite")
    command.upgrade(_cfg(url), "0006_analysis_not_null_ts")
    eng = create_engine(url)
    try:
        with pytest.raises(SchemaNotReadyError, match="0006_analysis_not_null_ts"):
            check_schema_for_production(_production(), db_engine=eng)
    finally:
        eng.dispose()


def test_production_starts_on_a_database_at_head(tmp_path):
    url = _url(tmp_path / "head.sqlite")
    command.upgrade(_cfg(url), "head")
    eng = create_engine(url)
    try:
        check_schema_for_production(_production(), db_engine=eng)  # no exception
    finally:
        eng.dispose()


def test_development_never_refuses_to_start():
    eng = _memory_engine()
    try:
        check_schema_for_production(Settings(APP_ENV="development"), db_engine=eng)
    finally:
        eng.dispose()


def test_the_production_app_does_not_finish_start_up_on_an_unmigrated_database(monkeypatch):
    eng = _memory_engine()
    monkeypatch.setattr(main_module, "engine", eng)
    app = create_app(_production())
    try:
        with pytest.raises(SchemaNotReadyError):
            with TestClient(app):
                pass
    finally:
        eng.dispose()


def test_the_refusal_message_contains_no_connection_details(tmp_path):
    url = _url(tmp_path / "secretname-behind.sqlite")
    command.upgrade(_cfg(url), "0006_analysis_not_null_ts")
    eng = create_engine(url)
    try:
        with pytest.raises(SchemaNotReadyError) as info:
            check_schema_for_production(_production(), db_engine=eng)
    finally:
        eng.dispose()
    assert "secretname" not in str(info.value) and "sqlite" not in str(info.value)


# --- reverse proxy and container contracts --------------------------------------------


def _caddy_zone(name: str) -> str:
    body = (REPO / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    m = re.search(rf"zone {name} \{{(.*?)\n\t\t\}}", body, re.S)
    assert m, f"rate_limit zone {name} missing"
    return m.group(1)


def test_caddy_rate_limits_sign_in_and_registration_per_client():
    body = (REPO / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    # The limiter runs inside the site block, before the requests are proxied.
    assert body.index("rate_limit {") < body.index("reverse_proxy @api api:8000")
    login = _caddy_zone("auth_login")
    assert "method POST" in login and "path /api/auth/login" in login
    assert "key {remote_host}" in login and "ipv6_prefix 64" in login
    assert re.search(r"events \d+", login) and re.search(r"window \d+[smh]", login)
    register = _caddy_zone("auth_register")
    assert "method POST" in register and "path /api/auth/register" in register
    assert "key {remote_host}" in register and "ipv6_prefix 64" in register
    assert re.search(r"events \d+", register) and re.search(r"window \d+[smh]", register)


def test_the_proxy_image_includes_the_rate_limit_module():
    dockerfile = (REPO / "deploy" / "caddy" / "Dockerfile").read_text(encoding="utf-8")
    assert "xcaddy build --with github.com/mholt/caddy-ratelimit" in dockerfile
    compose = (REPO / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "context: ./deploy/caddy" in compose


def test_only_the_proxy_publishes_ports_in_production():
    compose = (REPO / "docker-compose.prod.yml").read_text(encoding="utf-8")
    published = re.findall(r'^\s+- "(\d+):(\d+)"', compose, re.M)
    assert sorted(published) == [("443", "443"), ("80", "80")]
    assert compose.count("ports:") == 1
    # The proxy's ports: block is the only one, under the proxy service.
    assert compose.index("ports:") > compose.index("  proxy:")
    assert 'NEXT_PUBLIC_API_BASE_URL: ""' in compose


def test_the_api_image_runs_one_worker_as_a_non_root_user_in_production_mode():
    dockerfile = (REPO / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert '"--workers", "1"' in dockerfile  # the sign-in throttle lives in process memory
    assert "USER evidencex" in dockerfile
    assert "APP_ENV=production" in dockerfile and "COOKIE_SECURE=true" in dockerfile
    assert "--reload" not in dockerfile


def test_the_web_image_refuses_a_loopback_api_url():
    dockerfile = (REPO / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    assert "*localhost*|*127.0.0.1*" in dockerfile
    assert "next dev" not in dockerfile


def test_build_contexts_exclude_secrets_and_local_data():
    backend = (REPO / "backend" / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for entry in (".env", ".env.*", "var/", ".venv/"):
        assert entry in backend, entry  # database, evidence storage, models, secrets
    frontend = (REPO / "frontend" / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for entry in (".env", ".env.*", "node_modules/", ".next/"):
        assert entry in frontend, entry  # .env.local holds a localhost API URL
