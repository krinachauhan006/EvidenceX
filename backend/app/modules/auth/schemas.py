"""Auth and membership request/response schemas."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Role = Literal["viewer", "reviewer", "editor", "owner"]
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[A-Za-z]{2,24}$")


def _email(value: str) -> str:
    value = value.strip().lower()
    if not _EMAIL.match(value):
        raise ValueError("enter a valid e-mail address")
    return value


class RegisterRequest(BaseModel):
    email: str = Field(max_length=254)
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def _e(cls, v: str) -> str:
        return _email(v)

    @field_validator("display_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("display name must not be empty")
        return v


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def _e(cls, v: str) -> str:
        return v.strip().lower()


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    created_at: datetime


class SessionOut(BaseModel):
    user: UserOut
    expires_at: datetime
    # Present only when the first account claimed pre-existing (ownerless) cases.
    claimed_cases: int = 0


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role: Role
    added_at: datetime


class MemberList(BaseModel):
    items: list[MemberOut]
    my_role: Role


class MemberAdd(BaseModel):
    email: str = Field(max_length=254)
    role: Role

    @field_validator("email")
    @classmethod
    def _e(cls, v: str) -> str:
        return _email(v)


class MemberUpdate(BaseModel):
    role: Role
