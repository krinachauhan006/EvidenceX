"""Auth endpoints (public: register/login; session: me/logout) and case members."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.modules.auth.deps import authorize, current_user, session_token
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    LoginRequest,
    MemberAdd,
    MemberList,
    MemberUpdate,
    RegisterRequest,
    SessionOut,
    UserOut,
)
from app.modules.auth.service import AuthService, user_out

router = APIRouter(prefix="/api/auth", tags=["auth"])
members_router = APIRouter(
    prefix="/api/cases/{case_id}/members", tags=["auth"], dependencies=[Depends(authorize)]
)


def _service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(db)


def _set_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        s.session_cookie_name,
        token,
        max_age=s.session_days * 86400,
        httponly=True,  # not readable by page scripts
        secure=s.cookie_secure,
        samesite="lax",  # not sent on cross-site subrequests or form posts
        path="/",
    )


@router.post("/register", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest, response: Response, service: AuthService = Depends(_service)
) -> SessionOut:
    _user, claimed = service.register(payload)
    user, token, session = service.login(
        LoginRequest(email=payload.email, password=payload.password)
    )
    _set_cookie(response, token)
    return SessionOut(user=user_out(user), expires_at=session.expires_at, claimed_cases=claimed)


@router.post("/login", response_model=SessionOut)
def login(
    payload: LoginRequest, response: Response, service: AuthService = Depends(_service)
) -> SessionOut:
    user, token, session = service.login(payload)
    _set_cookie(response, token)
    return SessionOut(user=user_out(user), expires_at=session.expires_at)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, service: AuthService = Depends(_service)) -> Response:
    service.logout(session_token(request))
    out = Response(status_code=status.HTTP_204_NO_CONTENT)
    out.delete_cookie(get_settings().session_cookie_name, path="/")
    return out


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return user_out(user)


# --- members (owner-managed; listing open to every member) ----------------------


def _me(request: Request, case_id: uuid.UUID, service: AuthService):  # noqa: ANN202
    return service.membership(case_id, request.state.user.id)


@members_router.get("", response_model=MemberList)
def list_members(
    case_id: uuid.UUID, request: Request, service: AuthService = Depends(_service)
) -> MemberList:
    return service.members(case_id, _me(request, case_id, service))


@members_router.post("", response_model=MemberList, status_code=status.HTTP_201_CREATED)
def add_member(
    case_id: uuid.UUID,
    payload: MemberAdd,
    request: Request,
    service: AuthService = Depends(_service),
) -> MemberList:
    service.add_member(case_id, payload, request.state.user)
    return service.members(case_id, _me(request, case_id, service))


@members_router.patch("/{user_id}", response_model=MemberList)
def update_member(
    case_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: MemberUpdate,
    request: Request,
    service: AuthService = Depends(_service),
) -> MemberList:
    service.update_member(case_id, user_id, payload.role)
    return service.members(case_id, _me(request, case_id, service))


@members_router.delete("/{user_id}", response_model=MemberList)
def remove_member(
    case_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    service: AuthService = Depends(_service),
) -> MemberList:
    service.remove_member(case_id, user_id)
    return service.members(case_id, _me(request, case_id, service))
