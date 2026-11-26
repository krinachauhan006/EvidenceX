"""Authentication, sessions, roles and cross-user isolation (Phase 2).

Every protected route is enforced on the server; these tests call the API directly,
never relying on the UI to hide anything.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.modules.analysis.models import ReviewAction
from app.modules.auth.models import CaseMember
from app.modules.auth.schemas import RegisterRequest
from app.modules.auth.security import hash_password, verify_password
from app.modules.auth.service import AuthService
from app.modules.cases.models import Case
from tests.conftest import TEST_ACTOR, TEST_USER

CSV = b"shipment_id,arrival_time\nNS-1001,09:00\n"


def _case(client, title="Auth case") -> str:
    r = client.post("/api/cases", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _upload(client, case_id) -> TestClient:
    return client.post(
        f"/api/cases/{case_id}/evidence",
        files={"file": ("m.csv", CSV, "application/octet-stream")},
    )


def test_password_hashing_is_salted_scrypt():
    a, b = hash_password("a long passphrase"), hash_password("a long passphrase")
    assert a != b and a.startswith("scrypt$")
    assert verify_password("a long passphrase", a)
    assert not verify_password("wrong passphrase", a)
    assert not verify_password("x", "not-a-hash")


def test_unauthenticated_requests_are_rejected(client):
    anon = TestClient(client.app)
    for method, path in [
        ("get", "/api/cases"),
        ("post", "/api/cases"),
        ("get", "/api/workspace/summary"),
        ("get", "/api/audio/models"),
        ("get", "/api/auth/me"),
    ]:
        assert getattr(anon, method)(path).status_code == 401, path
    assert anon.get("/health").status_code == 200  # health stays public
    anon.close()


def test_session_cookie_flags_and_logout(client):
    other = TestClient(client.app)
    r = other.post(
        "/api/auth/login", json={"email": TEST_USER["email"], "password": TEST_USER["password"]}
    )
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert other.get("/api/auth/me").json()["email"] == TEST_USER["email"]
    assert other.post("/api/auth/logout").status_code == 204
    other.cookies.clear()
    assert other.get("/api/auth/me").status_code == 401
    other.close()


def test_logout_revokes_the_token_server_side(client):
    other = TestClient(client.app)
    other.post(
        "/api/auth/login", json={"email": TEST_USER["email"], "password": TEST_USER["password"]}
    )
    token = other.cookies.get("evx_session")
    other.post("/api/auth/logout")
    replay = TestClient(client.app)
    replay.cookies.set("evx_session", token)
    assert replay.get("/api/auth/me").status_code == 401  # a stolen old token is dead
    replay.close()
    other.close()


def test_login_failures_and_password_policy(client):
    anon = TestClient(client.app)
    bad = anon.post("/api/auth/login", json={"email": TEST_USER["email"], "password": "nope"})
    assert bad.status_code == 401
    unknown = anon.post("/api/auth/login", json={"email": "nobody@example.org", "password": "x"})
    assert unknown.status_code == 401
    assert bad.json()["detail"] == unknown.json()["detail"]  # no account enumeration
    weak = anon.post(
        "/api/auth/register",
        json={"email": "w@example.org", "display_name": "W", "password": "short"},
    )
    assert weak.status_code == 400
    dup = anon.post("/api/auth/register", json=TEST_USER)
    assert dup.status_code == 409
    anon.close()


def test_other_users_cannot_see_or_touch_a_case(client, make_user):
    case_id = _case(client)
    stranger = make_user("stranger@example.org")
    assert stranger.get("/api/cases").json()["total"] == 0
    for method, path in [
        ("get", f"/api/cases/{case_id}"),
        ("get", f"/api/cases/{case_id}/evidence"),
        ("get", f"/api/cases/{case_id}/claims"),
        ("get", f"/api/cases/{case_id}/graph"),
        ("post", f"/api/cases/{case_id}/analysis"),
        ("delete", f"/api/cases/{case_id}"),
    ]:
        assert getattr(stranger, method)(path).status_code == 404, path  # existence hidden
    assert _upload(stranger, case_id).status_code == 404


def test_roles_are_enforced_on_the_server(client, make_user):
    case_id = _case(client)
    viewer = make_user("viewer@example.org", "Viewer")
    reviewer = make_user("reviewer@example.org", "Reviewer")
    editor = make_user("editor@example.org", "Editor")
    for email, role in [
        ("viewer@example.org", "viewer"),
        ("reviewer@example.org", "reviewer"),
        ("editor@example.org", "editor"),
    ]:
        r = client.post(f"/api/cases/{case_id}/members", json={"email": email, "role": role})
        assert r.status_code == 201, r.text
    # viewer: read only
    assert viewer.get(f"/api/cases/{case_id}/evidence").status_code == 200
    assert _upload(viewer, case_id).status_code == 403
    assert viewer.patch(f"/api/cases/{case_id}", json={"title": "x"}).status_code == 403
    # reviewer: may review, may not upload or analyse
    assert _upload(reviewer, case_id).status_code == 403
    assert reviewer.post(f"/api/cases/{case_id}/analysis").status_code == 403
    # editor: may upload, may not delete the case or manage members
    assert _upload(editor, case_id).status_code == 201
    assert editor.delete(f"/api/cases/{case_id}").status_code == 403
    assert (
        editor.post(
            f"/api/cases/{case_id}/members", json={"email": "viewer@example.org", "role": "owner"}
        ).status_code
        == 403
    )
    assert (
        editor.post(
            f"/api/cases/{case_id}/consent", json={"ai_processing_allowed": True}
        ).status_code
        == 403
    )
    # everyone sees their own role
    assert viewer.get(f"/api/cases/{case_id}").json()["my_role"] == "viewer"
    members = client.get(f"/api/cases/{case_id}/members").json()
    assert members["my_role"] == "owner" and len(members["items"]) == 4


def test_last_owner_cannot_be_removed_or_demoted(client):
    case_id = _case(client)
    me = client.get("/api/auth/me").json()["id"]
    assert (
        client.patch(f"/api/cases/{case_id}/members/{me}", json={"role": "viewer"}).status_code
        == 409
    )
    assert client.delete(f"/api/cases/{case_id}/members/{me}").status_code == 409


def test_member_must_have_an_account(client):
    case_id = _case(client)
    r = client.post(
        f"/api/cases/{case_id}/members", json={"email": "missing@example.org", "role": "viewer"}
    )
    assert r.status_code == 404


def test_consent_is_owner_only_and_audited(client):
    case_id = _case(client)
    assert client.get(f"/api/cases/{case_id}").json()["ai_processing_allowed"] is False
    r = client.post(f"/api/cases/{case_id}/consent", json={"ai_processing_allowed": True})
    assert r.status_code == 200 and r.json()["ai_processing_allowed"] is True
    log = client.get(f"/api/cases/{case_id}/reviews").json()["items"]
    (entry,) = [x for x in log if x["action"] == "ai_consent"]
    assert entry["to_status"] == "allowed" and entry["reviewer"] == TEST_ACTOR


def _register(service: AuthService, email: str):  # noqa: ANN202
    return service.register(
        RegisterRequest(email=email, display_name=email.split("@")[0], password="a long password")
    )


def test_only_the_designated_account_receives_preexisting_cases(db_session):
    legacy = Case(title="Created before authentication", status="open")
    db_session.add(legacy)
    db_session.flush()
    service = AuthService(db_session, Settings(LEGACY_CASES_OWNER_EMAIL="Operator@Example.org "))
    # The FIRST account is not the designated one: it gets nothing.
    first, claimed_first = _register(service, "first@example.org")
    assert claimed_first == 0 and service.membership(legacy.id, first.id) is None
    op, claimed = _register(service, "operator@example.org")
    assert claimed == 1 and service.membership(legacy.id, op.id).role == "owner"
    later, claimed_later = _register(service, "later@example.org")
    assert claimed_later == 0 and service.membership(legacy.id, later.id) is None
    assert db_session.query(CaseMember).filter_by(case_id=legacy.id).count() == 1
    audit = [a for a in db_session.query(ReviewAction).filter_by(case_id=legacy.id)]
    assert [a.action for a in audit] == ["claim_ownerless_case"]
    assert audit[0].reviewer == "operator <operator@example.org>"


def test_without_a_designated_owner_nobody_receives_preexisting_cases(db_session):
    legacy = Case(title="Created before authentication", status="open")
    db_session.add(legacy)
    db_session.flush()
    service = AuthService(db_session, Settings(LEGACY_CASES_OWNER_EMAIL=""))
    user, claimed = _register(service, "first@example.org")
    assert claimed == 0
    assert db_session.query(CaseMember).filter_by(case_id=legacy.id).count() == 0
    # The case still exists, untouched, and the operator can assign it explicitly.
    assert db_session.get(Case, legacy.id).title == "Created before authentication"
    assert service.claim_legacy_cases(user, "operator") == 1
    assert service.membership(legacy.id, user.id).role == "owner"


def test_claiming_never_touches_cases_that_have_members(db_session, client):
    owned_id = _case(client, "Owned by the test user")
    service = AuthService(db_session, Settings(LEGACY_CASES_OWNER_EMAIL="op@example.org"))
    op, claimed = _register(service, "op@example.org")
    assert claimed == 0
    assert service.membership(uuid.UUID(owned_id), op.id) is None
