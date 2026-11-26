"""The local frontend works whether it is opened as localhost or 127.0.0.1."""

from __future__ import annotations

import pytest

from app.core.config import Settings


def test_default_origins_cover_both_loopback_names():
    assert Settings().cors_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]


@pytest.mark.parametrize("origin", ["http://localhost:3000", "http://127.0.0.1:3000"])
def test_local_origins_pass_cors_preflight_and_the_csrf_check(anon, origin):
    pre = anon.options(
        "/api/auth/login",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert pre.status_code == 200
    assert pre.headers["access-control-allow-origin"] == origin
    assert pre.headers["access-control-allow-credentials"] == "true"
    # A real (wrong-password) sign-in from that origin reaches the route: 401, not 403.
    r = anon.post(
        "/api/auth/login",
        json={"email": "investigator@example.org", "password": "wrong password"},
        headers={"Origin": origin},
    )
    assert r.status_code == 401


def test_other_origins_are_still_refused(anon):
    r = anon.post(
        "/api/auth/login",
        json={"email": "investigator@example.org", "password": "wrong password"},
        headers={"Origin": "http://evil.example"},
    )
    assert r.status_code == 403
