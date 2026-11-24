"""Pydantic request/response schemas for cases.

These are the transport contract; ORM models are never returned directly.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CaseStatus = Literal["open", "archived"]


def _validate_title(value: str) -> str:
    """Trim and require a non-empty title (Requirement 1.2)."""
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("title must not be empty")
    return trimmed


class CaseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        return _validate_title(v)


class CaseUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str | None = None
    status: CaseStatus | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        return _validate_title(v) if v is not None else None


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    status: CaseStatus
    created_at: datetime
    updated_at: datetime


class CaseList(BaseModel):
    items: list[CaseOut]
    total: int
    limit: int
    offset: int
