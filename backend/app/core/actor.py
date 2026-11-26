"""The authenticated user for the current request (set by the auth dependency).

Services read it to attribute review actions to the logged-in account instead of a
self-declared name. A ContextVar set in an async dependency propagates into the
threadpool where sync endpoints run.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class Actor:
    user_id: uuid.UUID
    email: str
    display_name: str
    role: str | None = None  # role in the case addressed by the request, if any

    @property
    def label(self) -> str:
        return f"{self.display_name} <{self.email}>"


_current: ContextVar[Actor | None] = ContextVar("evidencex_actor", default=None)


def set_actor(actor: Actor | None) -> None:
    _current.set(actor)


def current_actor() -> Actor | None:
    return _current.get()
