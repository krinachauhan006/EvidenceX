"""Registration, login, sessions and case membership."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db_types import as_utc, utcnow
from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    EvidenceXError,
    NotFoundError,
)
from app.core.logging import get_logger
from app.modules.analysis.audit import record_action
from app.modules.auth.models import ROLE_RANK, AuthSession, CaseMember, User
from app.modules.auth.schemas import (
    LoginRequest,
    MemberAdd,
    MemberList,
    MemberOut,
    RegisterRequest,
    UserOut,
)
from app.modules.auth.security import (
    DUMMY_HASH,
    hash_password,
    new_session_token,
    password_problem,
    token_digest,
    verify_password,
)
from app.modules.cases.models import Case

logger = get_logger(__name__)


class UnauthorizedError(EvidenceXError):
    status_code = 401
    message = "Sign in to continue."


class ForbiddenError(EvidenceXError):
    status_code = 403
    message = "Your role on this case does not allow this action."


class TooManyAttemptsError(EvidenceXError):
    status_code = 429
    message = "Too many failed sign-in attempts. Try again later."


class _Throttle:
    """In-process failed-login counter per e-mail address (single-process app)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fails: dict[str, list[float]] = {}

    def blocked(self, key: str, limit: int, window_s: float) -> bool:
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._fails.get(key, []) if now - t < window_s]
            self._fails[key] = recent
            return len(recent) >= limit

    def fail(self, key: str) -> None:
        with self._lock:
            self._fails.setdefault(key, []).append(time.monotonic())

    def clear(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


THROTTLE = _Throttle()


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id, email=user.email, display_name=user.display_name, created_at=user.created_at
    )


class AuthService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self._db = db
        self._settings = settings or get_settings()

    # --- accounts ------------------------------------------------------------------

    def register(self, req: RegisterRequest) -> tuple[User, int]:
        if not self._settings.registration_open:
            raise BadRequestError("registration is closed on this server")
        problem = password_problem(req.password)
        if problem:
            raise BadRequestError(problem)
        if self._db.scalar(select(User.id).where(User.email == req.email)):
            raise ConflictError("an account with this e-mail address already exists")
        designated = self._settings.legacy_cases_owner_email.strip().lower()
        user = User(
            email=req.email,
            display_name=req.display_name,
            password_hash=hash_password(req.password),
            is_active=True,
        )
        self._db.add(user)
        self._db.flush()
        claimed = 0
        if designated and req.email == designated:
            claimed = self.claim_legacy_cases(user, "registered with LEGACY_CASES_OWNER_EMAIL")
        self._db.commit()
        return user, claimed

    def claim_legacy_cases(self, user: User, reason: str) -> int:
        """Give every case WITHOUT members (created before authentication existed) to
        ``user`` as owner, so existing data stays reachable by one designated person.

        Only membership rows are added; the cases and their data are not modified.
        Cases that already have any member are never touched. Each claim is written to
        the case's audit chain. The caller commits.
        """
        owned = select(CaseMember.case_id)
        ids = list(self._db.scalars(select(Case.id).where(Case.id.not_in(owned))))
        for case_id in ids:
            self._db.add(CaseMember(case_id=case_id, user_id=user.id, role="owner"))
            record_action(
                self._db,
                case_id,
                "case",
                case_id,
                "claim_ownerless_case",
                reviewer=f"{user.display_name} <{user.email}>",
                payload={"user_id": str(user.id), "reason": reason},
            )
        if ids:
            self._db.flush()
            logger.info("designated account claimed %d pre-existing case(s)", len(ids))
        return len(ids)

    def login(self, req: LoginRequest) -> tuple[User, str, AuthSession]:
        s = self._settings
        if THROTTLE.blocked(req.email, s.login_max_failures, s.login_lockout_minutes * 60):
            raise TooManyAttemptsError()
        user = self._db.scalar(select(User).where(User.email == req.email))
        ok = verify_password(req.password, user.password_hash if user else DUMMY_HASH)
        if not user or not ok or not user.is_active:
            THROTTLE.fail(req.email)
            raise UnauthorizedError("The e-mail address or password is incorrect.")
        THROTTLE.clear(req.email)
        token = new_session_token()
        session = AuthSession(
            user_id=user.id,
            token_hash=token_digest(token),
            expires_at=utcnow() + timedelta(days=s.session_days),
            revoked=False,
        )
        user.last_login_at = utcnow()
        self._db.add(session)
        self._db.commit()
        return user, token, session

    def user_for_token(self, token: str | None) -> tuple[User, AuthSession] | None:
        if not token or len(token) > 200:
            return None
        session = self._db.scalar(
            select(AuthSession).where(AuthSession.token_hash == token_digest(token))
        )
        if session is None or session.revoked or as_utc(session.expires_at) <= utcnow():
            return None
        user = self._db.get(User, session.user_id)
        if user is None or not user.is_active:
            return None
        return user, session

    def logout(self, token: str | None) -> None:
        found = self.user_for_token(token)
        if found:
            found[1].revoked = True
            self._db.commit()

    # --- membership ----------------------------------------------------------------

    def membership(self, case_id: uuid.UUID, user_id: uuid.UUID) -> CaseMember | None:
        return self._db.scalar(
            select(CaseMember).where(CaseMember.case_id == case_id, CaseMember.user_id == user_id)
        )

    def add_owner(self, case_id: uuid.UUID, user: User) -> None:
        self._db.add(CaseMember(case_id=case_id, user_id=user.id, role="owner"))
        self._db.commit()

    def members(self, case_id: uuid.UUID, me: CaseMember) -> MemberList:
        rows = self._db.execute(
            select(CaseMember, User)
            .join(User, User.id == CaseMember.user_id)
            .where(CaseMember.case_id == case_id)
            .order_by(CaseMember.created_at)
        ).all()
        return MemberList(
            items=[
                MemberOut(
                    user_id=u.id,
                    email=u.email,
                    display_name=u.display_name,
                    role=m.role,
                    added_at=m.created_at,
                )  # type: ignore[arg-type]
                for m, u in rows
            ],
            my_role=me.role,  # type: ignore[arg-type]
        )

    def _owners(self, case_id: uuid.UUID) -> int:
        return int(
            self._db.scalar(
                select(func.count())
                .select_from(CaseMember)
                .where(CaseMember.case_id == case_id, CaseMember.role == "owner")
            )
            or 0
        )

    def add_member(self, case_id: uuid.UUID, req: MemberAdd, actor: User) -> None:
        """Controlled workflow: the person must already have an account. No e-mail
        invitations are sent (no mail service is configured)."""
        user = self._db.scalar(select(User).where(User.email == req.email))
        if user is None:
            raise NotFoundError(
                "no account uses this e-mail address; ask the person to register first"
            )
        if self.membership(case_id, user.id):
            raise ConflictError("this person is already a member of the case")
        self._db.add(
            CaseMember(case_id=case_id, user_id=user.id, role=req.role, added_by_user_id=actor.id)
        )
        record_action(
            self._db,
            case_id,
            "case_member",
            user.id,
            "add_member",
            to_status=req.role,
            payload={"email": user.email},
        )
        self._db.commit()

    def update_member(self, case_id: uuid.UUID, user_id: uuid.UUID, role: str) -> None:
        member = self.membership(case_id, user_id)
        if member is None:
            raise NotFoundError("member not found")
        if member.role == "owner" and role != "owner" and self._owners(case_id) <= 1:
            raise ConflictError("a case must keep at least one owner")
        before, member.role = member.role, role
        record_action(
            self._db,
            case_id,
            "case_member",
            user_id,
            "change_role",
            from_status=before,
            to_status=role,
        )
        self._db.commit()

    def remove_member(self, case_id: uuid.UUID, user_id: uuid.UUID) -> None:
        member = self.membership(case_id, user_id)
        if member is None:
            raise NotFoundError("member not found")
        if member.role == "owner" and self._owners(case_id) <= 1:
            raise ConflictError("a case must keep at least one owner")
        record_action(
            self._db, case_id, "case_member", user_id, "remove_member", from_status=member.role
        )
        self._db.delete(member)
        self._db.commit()

    @staticmethod
    def rank(role: str) -> int:
        return ROLE_RANK.get(role, -1)
