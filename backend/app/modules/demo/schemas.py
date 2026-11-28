"""Response schemas for the self-service demo case."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel


class DemoFileOut(BaseModel):
    name: str
    processing_status: str
    # Processed by the separate local processing worker (EXTERNAL_WORKER_MIMES), not by
    # this server: "pending" here means "waiting for the worker", not "stuck".
    external_worker: bool


class DemoCaseOut(BaseModel):
    case_id: uuid.UUID
    status: Literal["created", "exists", "repaired"]
    title: str
    files: list[DemoFileOut]
    # Files this server started processing for this request (PDF, CSV, e-mail).
    queued: int
    # Files waiting for the local processing worker (images, audio, video).
    awaiting_worker: int


class DemoCaseRef(BaseModel):
    """The signed-in user's demo case, if they have loaded one."""

    case_id: uuid.UUID | None
