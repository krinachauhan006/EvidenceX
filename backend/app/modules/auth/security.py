"""Password hashing and session tokens (standard library only).

Passwords: scrypt (memory-hard KDF, RFC 7914) with a random 16-byte salt per
password. Parameters n=2**14, r=8, p=1 (~16 MiB) follow common guidance for
interactive logins. The stored format is self-describing so parameters can be
raised later without breaking existing hashes.

Session tokens: 32 random bytes (URL-safe). Only SHA-256(token) is stored.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
DKLEN = 32
# Lengths count Unicode code points (Python ``len``); the frontend counts the same
# way (``[...password].length``) so both sides agree on non-ASCII passwords.
MIN_PASSWORD = 8
MAX_PASSWORD = 256


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=DKLEN,
        maxmem=64 * 1024 * 1024,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = _unb64(digest)
        got = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
            maxmem=64 * 1024 * 1024,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected)


# A fixed hash used to spend the same time on unknown e-mail addresses, so login
# timing does not reveal which accounts exist.
DUMMY_HASH = hash_password("evidencex-timing-equalizer")


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"the password must have at least {MIN_PASSWORD} characters"
    if len(password) > MAX_PASSWORD:
        return f"the password must have at most {MAX_PASSWORD} characters"
    if password.strip() != password or not password.strip():
        return "the password must not start or end with spaces"
    return None
