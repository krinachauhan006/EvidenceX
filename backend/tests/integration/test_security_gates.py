"""Security gates for Phase 2 authentication and authorization.

These tests enumerate EVERY registered API route, so a new endpoint that forgets the
``authorize`` dependency fails here automatically. They use explicit anonymous and
second-user clients; the auto-signed-in ``client`` fixture is only the case owner.
All data is synthetic.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.db_types import utcnow
from app.modules.auth import router as auth_router_module
from app.modules.auth.models import AuthSession
from tests.conftest import TEST_USER

PUBLIC = {
    ("GET", "/health"),
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),  # clears a cookie; harmless without one
}
CSV = b"shipment_id,arrival_time,location\nNS-1001,09:00,Warehouse A\n"
CASE_SCOPED_IDS = (
    "evidence_id",
    "claim_id",
    "entity_id",
    "contradiction_id",
    "relationship_id",
    "report_id",
    "event_id",
    "segment_id",
    "user_id",
    "extraction_id",
)


def api_routes(app) -> list[tuple[str, str]]:  # noqa: ANN001
    """Every operation the app serves, from its generated OpenAPI document.

    FastAPI 0.16x wraps included routers, so ``app.routes`` no longer lists their
    endpoints; the OpenAPI document is the inventory. Routes hidden from the schema
    would be missed, so the test also checks that none of the app's routes are hidden.
    """
    out = []
    for path, ops in app.openapi()["paths"].items():
        for method in ops:
            if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                out.append((method.upper(), path))
    hidden = [r for r in app.routes if isinstance(r, APIRoute) and not r.include_in_schema]
    assert not hidden, hidden
    app_dir = Path(__file__).resolve().parents[2] / "app"
    assert not [
        p for p in app_dir.rglob("*.py") if "include_in_schema=False" in p.read_text("utf-8")
    ]
    return sorted(set(out))


def fill(path: str, ids: dict[str, str]) -> str:
    def sub(m: re.Match) -> str:
        name = m.group(1)
        if name == "page":
            return "1"
        return ids.get(name) or str(uuid.uuid4())

    return re.sub(r"\{([^}:]+)(?::[^}]+)?\}", sub, path)


def call(c: TestClient, method: str, path: str):  # noqa: ANN201
    if method in ("POST", "PUT", "PATCH"):
        return c.request(method, path, json={})
    return c.request(method, path)


@pytest.fixture
def owned(client) -> dict[str, str]:
    """A case owned by the default client, with evidence, an analysis and a report."""
    case_id = client.post("/api/cases", json={"title": "Owner-only case Zeta"}).json()["id"]
    ev = client.post(
        f"/api/cases/{case_id}/evidence",
        files={"file": ("zeta-ledger.csv", CSV, "application/octet-stream")},
    ).json()
    client.post(f"/api/cases/{case_id}/evidence/{ev['id']}/process", json={})
    assert client.post(f"/api/cases/{case_id}/analysis").status_code == 202
    report = client.post(f"/api/cases/{case_id}/reports", json={"kind": "investigation"})
    assert report.status_code == 201, report.text
    claims = client.get(f"/api/cases/{case_id}/claims").json()["items"]
    entities = client.get(f"/api/cases/{case_id}/entities").json()["items"]
    segs = client.get(f"/api/cases/{case_id}/evidence/{ev['id']}/segments").json()["items"]
    return {
        "case_id": case_id,
        "evidence_id": ev["id"],
        "report_id": report.json()["id"],
        "claim_id": claims[0]["id"] if claims else str(uuid.uuid4()),
        "entity_id": entities[0]["id"] if entities else str(uuid.uuid4()),
        "segment_id": segs[0]["id"] if segs else str(uuid.uuid4()),
    }


# --- 1. unauthenticated access ----------------------------------------------------------


def test_route_inventory_is_large_enough_to_be_meaningful(client):
    routes = api_routes(client.app)
    assert len(routes) >= 60
    assert sum(1 for _, p in routes if "{case_id}" in p) >= 45


def test_every_protected_route_rejects_anonymous_callers(anon, owned):
    checked = 0
    for method, path in api_routes(anon.app):
        if (method, path) in PUBLIC:
            continue
        r = call(anon, method, fill(path, owned))
        assert r.status_code == 401, (method, path, r.status_code)
        assert "Zeta" not in r.text  # nothing about the case leaks
        checked += 1
    assert checked >= 60


def test_garbage_or_foreign_tokens_are_rejected(anon, owned):
    url = f"/api/cases/{owned['case_id']}"
    for value in ["x", "a" * 199, "a" * 5000, str(uuid.uuid4())]:
        anon.cookies.set("evx_session", value)
        assert anon.get(url).status_code == 401
        anon.cookies.clear()
        assert anon.get(url, headers={"Authorization": f"Bearer {value}"}).status_code == 401


# --- 2. other users' cases ---------------------------------------------------------------


def test_a_stranger_gets_404_on_every_case_scoped_route(make_user, owned):
    stranger = make_user("stranger@example.org", "Stranger")
    checked = 0
    for method, path in api_routes(stranger.app):
        if "{case_id}" not in path:
            continue
        r = call(stranger, method, fill(path, owned))
        assert r.status_code == 404, (method, path, r.status_code, r.text[:200])
        assert "Zeta" not in r.text and "zeta-ledger" not in r.text
        checked += 1
    assert checked >= 45


def test_a_stranger_sees_nothing_in_lists_and_totals(make_user, owned):
    stranger = make_user("stranger2@example.org")
    assert stranger.get("/api/cases").json()["total"] == 0
    summary = stranger.get("/api/workspace/summary").json()
    assert summary["cases"]["total"] == 0 and summary["evidence"]["total"] == 0
    assert summary["recent_cases"] == [] and summary["processing_activity"] == []


def test_ids_from_another_case_are_not_reachable_through_my_case(client, owned):
    """The same user owns both cases; ids must still be scoped to the case in the URL."""
    mine = client.post("/api/cases", json={"title": "Second case"}).json()["id"]
    for path in [
        f"/api/cases/{mine}/evidence/{owned['evidence_id']}",
        f"/api/cases/{mine}/evidence/{owned['evidence_id']}/download",
        f"/api/cases/{mine}/evidence/{owned['evidence_id']}/segments",
        f"/api/cases/{mine}/claims/{owned['claim_id']}",
        f"/api/cases/{mine}/entities/{owned['entity_id']}",
        f"/api/cases/{mine}/reports/{owned['report_id']}",
        f"/api/cases/{mine}/reports/{owned['report_id']}/download",
    ]:
        assert client.get(path).status_code == 404, path
    graph = client.get(f"/api/cases/{mine}/graph/export", params={"format": "json"})
    assert graph.status_code == 200 and b"zeta-ledger" not in graph.content
    graphml = client.get(f"/api/cases/{mine}/graph/export", params={"format": "graphml"})
    assert graphml.status_code == 200 and b"zeta-ledger" not in graphml.content
    hits = client.get(f"/api/cases/{mine}/search", params={"q": "NS-1001"}).json()
    assert hits["total"] == 0


def test_a_viewer_cannot_change_anything(client, make_user, owned):
    case_id = owned["case_id"]
    viewer = make_user("viewer2@example.org", "Viewer")
    client.post(
        f"/api/cases/{case_id}/members", json={"email": "viewer2@example.org", "role": "viewer"}
    )
    checked = 0
    for method, path in api_routes(viewer.app):
        if "{case_id}" not in path or method == "GET" or path.endswith("/ask"):
            continue
        r = call(viewer, method, fill(path, owned))
        assert r.status_code == 403, (method, path, r.status_code)
        checked += 1
    assert checked >= 20
    # Reading is allowed, including exports and the report file.
    assert viewer.get(f"/api/cases/{case_id}/graph/export").status_code == 200
    assert (
        viewer.get(f"/api/cases/{case_id}/reports/{owned['report_id']}/download").status_code == 200
    )


def test_removed_member_loses_access_immediately(client, make_user, owned):
    case_id = owned["case_id"]
    member = make_user("temp@example.org", "Temp")
    client.post(
        f"/api/cases/{case_id}/members", json={"email": "temp@example.org", "role": "editor"}
    )
    assert member.get(f"/api/cases/{case_id}").status_code == 200
    uid = next(
        m["user_id"]
        for m in client.get(f"/api/cases/{case_id}/members").json()["items"]
        if m["email"] == "temp@example.org"
    )
    assert client.delete(f"/api/cases/{case_id}/members/{uid}").status_code == 200
    assert member.get(f"/api/cases/{case_id}").status_code == 404


# --- 3. sessions, tokens and cookies -----------------------------------------------------------


def _login(c: TestClient):  # noqa: ANN202
    r = c.post(
        "/api/auth/login", json={"email": TEST_USER["email"], "password": TEST_USER["password"]}
    )
    assert r.status_code == 200, r.text
    return r


def test_only_a_hash_of_the_token_is_stored(client, anon, db_session):
    _login(anon)
    token = anon.cookies.get("evx_session")
    assert token and len(token) >= 40
    rows = db_session.query(AuthSession).all()
    assert all(row.token_hash != token for row in rows)
    assert hashlib.sha256(token.encode()).hexdigest() in {row.token_hash for row in rows}


def test_expired_sessions_are_rejected(anon, db_session):
    _login(anon)
    digest = hashlib.sha256(anon.cookies.get("evx_session").encode()).hexdigest()
    assert anon.get("/api/auth/me").status_code == 200
    row = db_session.query(AuthSession).filter_by(token_hash=digest).one()
    row.expires_at = utcnow() - timedelta(seconds=1)
    db_session.flush()
    assert anon.get("/api/auth/me").status_code == 401
    assert anon.get("/api/cases").status_code == 401


def test_logout_ends_only_that_session(client, anon):
    _login(anon)
    r = anon.post("/api/auth/logout")
    assert r.status_code == 204
    cleared = r.headers["set-cookie"].lower()
    assert "evx_session=" in cleared and ("max-age=0" in cleared or "expires=" in cleared)
    assert anon.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me").status_code == 200  # the other session still works


def test_cookie_attributes(anon, monkeypatch):
    r = _login(anon)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert "domain=" not in cookie  # host-only cookie
    assert f"max-age={7 * 86400}" in cookie
    assert "secure" not in cookie.replace("samesite", "")  # local http default
    secure = Settings(COOKIE_SECURE=True)
    monkeypatch.setattr(auth_router_module, "get_settings", lambda: secure)
    assert "; secure" in _login(anon).headers["set-cookie"].lower()


def test_session_tokens_are_never_returned_in_bodies(anon):
    r = _login(anon)
    token = anon.cookies.get("evx_session")
    assert token not in r.text and "token" not in r.json()


def test_bearer_tokens_work_for_non_browser_clients(client, anon):
    _login(anon)
    token = anon.cookies.get("evx_session")
    plain = TestClient(client.app)
    assert (
        plain.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    )
    plain.close()


# --- 4. CSRF -----------------------------------------------------------------------------------


def test_cross_origin_writes_are_refused_before_any_route_runs(client):
    before = client.get("/api/cases").json()["total"]
    evil = client.post(
        "/api/cases", json={"title": "csrf"}, headers={"Origin": "https://evil.example"}
    )
    assert evil.status_code == 403 and evil.json()["detail"] == "cross-origin request refused"
    meta = client.post(
        "/api/cases", json={"title": "csrf"}, headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert meta.status_code == 403
    login = client.post(
        "/api/auth/login",
        json={"email": TEST_USER["email"], "password": TEST_USER["password"]},
        headers={"Origin": "https://evil.example"},
    )
    assert login.status_code == 403  # no login CSRF either
    assert client.get("/api/cases").json()["total"] == before  # nothing was created


def test_trusted_origins_and_reads_are_allowed(client):
    allowed = Settings().cors_origins[0]
    ok = client.post("/api/cases", json={"title": "from the app"}, headers={"Origin": allowed})
    assert ok.status_code == 201
    same_site = client.post(
        "/api/cases", json={"title": "same site"}, headers={"Sec-Fetch-Site": "same-site"}
    )
    assert same_site.status_code == 201
    read = client.get("/api/cases", headers={"Origin": "https://evil.example"})
    assert read.status_code == 200  # reads are protected by CORS, not refused here
    assert "access-control-allow-origin" not in read.headers


def test_json_endpoints_do_not_accept_form_posts(client):
    r = client.post(
        "/api/cases",
        content=b'{"title": "form"}',
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 422  # a cross-site HTML form cannot send application/json
