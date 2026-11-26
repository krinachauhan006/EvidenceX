"""Password policy: minimum 8 characters (Unicode code points), consistent errors,
and no password ever echoed back in an error response."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.modules.auth.security import MAX_PASSWORD, MIN_PASSWORD, password_problem
from tests.conftest import TEST_USER


def _register(anon: TestClient, email: str, password: str):  # noqa: ANN202
    return anon.post(
        "/api/auth/register", json={"email": email, "display_name": "P", "password": password}
    )


# --- unit: the single rule both endpoints use --------------------------------------


def test_minimum_is_eight():
    assert MIN_PASSWORD == 8


@pytest.mark.parametrize(
    "password",
    [
        "abcdefgh",
        "12345678",
        "pässwörd",
        "密码密码密码密码",
        "🔒🔒🔒🔒🔒🔒🔒🔒",
        "a" * MAX_PASSWORD,
    ],
)
def test_eight_or_more_code_points_are_accepted(password):
    assert password_problem(password) is None


@pytest.mark.parametrize("password", ["", "abcdefg", "pässwör", "🔒🔒🔒🔒🔒🔒🔒"])
def test_seven_or_fewer_code_points_are_rejected(password):
    assert password_problem(password) == "the password must have at least 8 characters"


def test_length_counts_code_points_not_bytes():
    # 7 emoji are 28 UTF-8 bytes and 14 UTF-16 units, but still only 7 characters.
    assert password_problem("🔒" * 7) is not None
    assert password_problem("🔒" * 8) is None


def test_other_rules_are_unchanged():
    assert password_problem("a" * (MAX_PASSWORD + 1)) is not None
    assert password_problem(" leading spaces") is not None
    assert password_problem("trailing spaces ") is not None
    assert password_problem("        ") is not None


# --- API ------------------------------------------------------------------------------


def test_seven_character_password_is_rejected_by_the_api(anon):
    r = _register(anon, "seven@example.org", "abcdefg")
    assert r.status_code == 400
    assert r.json()["detail"] == "the password must have at least 8 characters"
    assert "abcdefg" not in r.text


def test_eight_character_password_is_accepted_and_can_sign_in(anon):
    r = _register(anon, "eight@example.org", "abcdefgh")
    assert r.status_code == 201, r.text
    assert "abcdefgh" not in r.text
    other = TestClient(anon.app)
    login = other.post(
        "/api/auth/login", json={"email": "eight@example.org", "password": "abcdefgh"}
    )
    assert login.status_code == 200
    assert other.get("/api/auth/me").json()["email"] == "eight@example.org"
    other.close()


def test_longer_and_unicode_passwords_are_accepted(anon):
    assert _register(anon, "long@example.org", "a much longer passphrase 2026").status_code == 201
    assert _register(anon, "uni@example.org", "pässwörd").status_code == 201
    other = TestClient(anon.app)
    assert (
        other.post(
            "/api/auth/login", json={"email": "uni@example.org", "password": "pässwörd"}
        ).status_code
        == 200
    )
    other.close()


def test_existing_account_still_signs_in(client):
    """The account registered by the fixture (before this test) is unaffected."""
    other = TestClient(client.app)
    r = other.post(
        "/api/auth/login", json={"email": TEST_USER["email"], "password": TEST_USER["password"]}
    )
    assert r.status_code == 200
    other.close()


def test_login_does_not_apply_the_registration_minimum(anon):
    """Sign-in compares against the stored hash; a short wrong password is just wrong."""
    r = anon.post("/api/auth/login", json={"email": TEST_USER["email"], "password": "short"})
    assert r.status_code == 401


def test_validation_errors_never_echo_the_password(anon):
    secret = "my-secret-passphrase-123"
    # Missing display_name: FastAPI would normally echo the whole body as "input".
    missing = anon.post("/api/auth/register", json={"email": "m@example.org", "password": secret})
    assert missing.status_code == 422
    assert secret not in missing.text
    assert all(set(e) <= {"type", "loc", "msg"} for e in missing.json()["detail"])
    # Over the maximum length: the field value itself would be echoed.
    too_long = "x" * 300
    r = _register(anon, "t@example.org", too_long)
    assert r.status_code == 422 and too_long not in r.text
    # Login with a wrong-typed field.
    r = anon.post("/api/auth/login", json={"email": ["x"], "password": secret})
    assert r.status_code == 422 and secret not in r.text
