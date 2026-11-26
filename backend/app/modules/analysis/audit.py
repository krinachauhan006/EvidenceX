"""Append-only audit trail with a per-case tamper-evident hash chain.

Each new ``review_actions`` row stores ``prev_hash`` (the hash of the case's previous
chained row) and ``hash = sha256(prev_hash | canonical fields)``. Any later edit,
deletion or reordering of a chained row breaks verification from that point on.
Rows written before migration 0007 have no hash and are reported as "legacy"; they
are never rewritten.

This makes changes evident; it does not make them impossible (whoever controls the
database could rebuild the whole chain). Anchoring the latest hash outside the
database would close that gap and is documented as future work.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.actor import current_actor
from app.core.db_types import as_utc, utcnow
from app.modules.analysis.models import ReviewAction

DEFAULT_REVIEWER = "unspecified"
GENESIS = "0" * 64


def _canonical(row: ReviewAction) -> str:
    return json.dumps(
        {
            "case_id": row.case_id.hex,
            "target_type": row.target_type,
            "target_id": row.target_id.hex,
            "action": row.action,
            "from": row.from_status,
            "to": row.to_status,
            "note": row.note,
            "payload": row.payload or {},
            "reviewer": row.reviewer,
            "created_at": as_utc(row.created_at).isoformat(timespec="microseconds"),
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )


def compute_hash(prev_hash: str, row: ReviewAction) -> str:
    return hashlib.sha256(f"{prev_hash}|{_canonical(row)}".encode()).hexdigest()


def _last_hash(db: Session, case_id: uuid.UUID) -> str:
    # Pending (unflushed) rows of this session come first: two actions recorded in
    # one transaction must chain to each other.
    pending = [o for o in db.new if isinstance(o, ReviewAction) and o.case_id == case_id and o.hash]
    if pending:
        return max(pending, key=lambda o: as_utc(o.created_at)).hash  # type: ignore[return-value]
    last = db.scalars(
        select(ReviewAction.hash)
        .where(ReviewAction.case_id == case_id, ReviewAction.hash.is_not(None))
        .order_by(ReviewAction.created_at.desc())
        .limit(1)
    ).first()
    return last or GENESIS


def record_action(
    db: Session,
    case_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
    action: str,
    *,
    from_status: str | None = None,
    to_status: str | None = None,
    note: str | None = None,
    reviewer: str | None = None,
    payload: dict[str, Any] | None = None,
) -> ReviewAction:
    """Append one audited action. The logged-in account, when present, is recorded
    as the reviewer; a self-declared name is kept in the payload for context only."""
    actor = current_actor()
    payload = dict(payload or {})
    name = (reviewer or "").strip()
    if actor is not None:
        if name and name != actor.label:
            payload["declared_reviewer"] = name[:128]
        name = actor.label
        payload["user_id"] = str(actor.user_id)
    row = ReviewAction(
        id=uuid.uuid4(),
        case_id=case_id,
        target_type=target_type,
        target_id=target_id,
        action=action,
        from_status=from_status,
        to_status=to_status,
        note=(note or None),
        payload=payload,
        reviewer=(name or DEFAULT_REVIEWER)[:128],
        created_at=utcnow(),
    )
    row.prev_hash = _last_hash(db, case_id)
    row.hash = compute_hash(row.prev_hash, row)
    db.add(row)
    return row


def verify_chain(db: Session, case_id: uuid.UUID) -> dict[str, Any]:
    rows = list(
        db.scalars(
            select(ReviewAction)
            .where(ReviewAction.case_id == case_id)
            .order_by(ReviewAction.created_at, ReviewAction.id)
        )
    )
    legacy = [r for r in rows if r.hash is None]
    chained = [r for r in rows if r.hash is not None]
    prev = GENESIS
    for i, row in enumerate(chained):
        if row.prev_hash != prev:
            return {
                "intact": False,
                "checked": i,
                "broken_at": str(row.id),
                "reason": "the link to the previous action does not match",
                "legacy_unchained": len(legacy),
                "total": len(rows),
            }
        if compute_hash(prev, row) != row.hash:
            return {
                "intact": False,
                "checked": i,
                "broken_at": str(row.id),
                "reason": "the action's content no longer matches its hash",
                "legacy_unchained": len(legacy),
                "total": len(rows),
            }
        prev = row.hash
    return {
        "intact": True,
        "checked": len(chained),
        "broken_at": None,
        "reason": None,
        "legacy_unchained": len(legacy),
        "total": len(rows),
        "head": prev if chained else None,
    }
