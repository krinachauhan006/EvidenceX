"""Unit tests for case validation and service-level rules.

These use an in-memory SQLite session directly (no HTTP layer) and never touch the
network or any AI service.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.core.exceptions import NotFoundError
from app.modules.cases.schemas import CaseCreate, CaseUpdate
from app.modules.cases.service import MAX_LIMIT, CaseService

# --- schema / title validation -------------------------------------------------


def test_title_is_trimmed():
    assert CaseCreate(title="  Operation Nightfall  ").title == "Operation Nightfall"


@pytest.mark.parametrize("bad", ["", "   ", "\t\n"])
def test_empty_title_rejected(bad):
    with pytest.raises(ValidationError):
        CaseCreate(title=bad)


def test_too_long_title_rejected():
    with pytest.raises(ValidationError):
        CaseCreate(title="x" * 201)


def test_update_title_trimmed_and_optional():
    assert CaseUpdate().title is None
    assert CaseUpdate(title="  Case A ").title == "Case A"


def test_update_invalid_status_rejected():
    with pytest.raises(ValidationError):
        CaseUpdate(status="deleted")  # type: ignore[arg-type]


# --- service rules --------------------------------------------------------------


def test_get_missing_case_raises_not_found(db_session):
    service = CaseService(db_session)
    with pytest.raises(NotFoundError):
        service.get(uuid.uuid4())


def test_archive_preserves_data_and_hides_from_default_list(db_session):
    service = CaseService(db_session)
    created = service.create(CaseCreate(title="To Archive", description="keep me"))

    archived = service.archive(created.id)
    assert archived.status == "archived"
    # Archive preserves all data.
    assert archived.title == "To Archive"
    assert archived.description == "keep me"

    # Hidden from the default list.
    default_items, default_total, _, _ = service.list(status=None, limit=50, offset=0)
    assert all(c.id != created.id for c in default_items)
    assert default_total == 0

    # Visible when explicitly filtering archived.
    archived_items, archived_total, _, _ = service.list(
        status="archived", limit=50, offset=0
    )
    assert any(c.id == created.id for c in archived_items)
    assert archived_total == 1


def test_list_limit_is_capped(db_session):
    service = CaseService(db_session)
    _, _, used_limit, _ = service.list(status=None, limit=10_000, offset=-5)
    assert used_limit == MAX_LIMIT


def test_delete_is_scoped_to_one_case(db_session):
    service = CaseService(db_session)
    a = service.create(CaseCreate(title="Case A"))
    b = service.create(CaseCreate(title="Case B"))

    service.delete(a.id)

    # A is gone; B is untouched (no accidental deletion of unrelated cases).
    with pytest.raises(NotFoundError):
        service.get(a.id)
    assert service.get(b.id).id == b.id
