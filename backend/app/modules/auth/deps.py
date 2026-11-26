"""Server-side authentication and case-level authorization.

``authorize`` is attached to every protected router. It
1. resolves the session cookie (or ``Authorization: Bearer``) to an active user
   -> 401 otherwise;
2. for any path containing a ``case_id``: requires a membership -> 404 when the
   caller is not a member (existence is not revealed), and a role at least as high
   as the action needs -> 403 otherwise;
3. publishes the user as the request's actor (used for audit attribution).

Required role per request (``required_role``):
- read (GET/HEAD/OPTIONS) .............................. viewer
- review decisions (``/review``, ``/reviews``, ``/alternatives``), report export . reviewer
- member management, AI consent, deleting the case ..... owner
- every other write (upload, process, analyse, edit) ... editor
"""

from __future__ import annotations

import re
import uuid

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.actor import Actor, set_actor
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.modules.auth.models import ROLE_RANK, User
from app.modules.auth.service import AuthService, ForbiddenError, UnauthorizedError

_READ = {"GET", "HEAD", "OPTIONS"}
_REVIEW = re.compile(r"/(review|reviews|alternatives)$")
_CASE_ROOT = re.compile(r"^/api/cases/[^/]+$")


def required_role(method: str, path: str) -> str:
    if method in _READ:
        return "viewer"
    if "/members" in path or path.endswith("/consent"):
        return "owner"
    if method == "DELETE" and _CASE_ROOT.match(path):
        return "owner"
    if path.endswith("/ask"):
        return "viewer"  # a question changes nothing (AI use still needs case consent)
    if _REVIEW.search(path) or path.endswith("/reports") or path.endswith("/events"):
        return "reviewer"
    return "editor"


def session_token(request: Request) -> str | None:
    token = request.cookies.get(get_settings().session_cookie_name)
    if token:
        return token
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


async def current_user(request: Request, db: Session = Depends(get_db)) -> User:  # noqa: B008
    found = AuthService(db).user_for_token(session_token(request))
    if found is None:
        set_actor(None)
        raise UnauthorizedError()
    user = found[0]
    request.state.user = user
    set_actor(Actor(user_id=user.id, email=user.email, display_name=user.display_name))
    return user


async def authorize(
    request: Request,
    user: User = Depends(current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> User:
    raw = request.path_params.get("case_id")
    if raw is None:
        return user
    try:
        case_id = uuid.UUID(str(raw))
    except ValueError:
        return user  # FastAPI's own validation answers 422 for a malformed id
    member = AuthService(db).membership(case_id, user.id)
    if member is None:
        raise NotFoundError("case not found")
    need = required_role(request.method, request.url.path)
    if ROLE_RANK[member.role] < ROLE_RANK[need]:
        raise ForbiddenError(
            f"This action needs the '{need}' role; your role on this case is '{member.role}'."
        )
    request.state.case_role = member.role
    set_actor(
        Actor(user_id=user.id, email=user.email, display_name=user.display_name, role=member.role)
    )
    return user
