"""Self-service demo case: POST /api/demo/missing-shipment.

A signed-in user loads their OWN copy of the fictional Missing Shipment case. The
tests use the API with the deployment's worker gate on (images, audio and video are
left to the local processing worker), the test database and temporary storage.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import func, select

from app.core import config as config_module
from app.demo_seed import (
    BUNDLED_DEMO_DIR,
    DEMO_FILES,
    DEMO_TITLE,
    REPO_DEMO_DIR,
    SeedError,
    provision_demo_case,
)
from app.modules.cases.models import Case
from app.modules.demo.router import get_session_factory
from app.modules.evidence.models import Evidence
from app.modules.evidence.service import EvidenceService

URL = "/api/demo/missing-shipment"
WORKER_MIMES = (
    "image/png,image/jpeg,image/webp,audio/wav,audio/mpeg,audio/mp4,"
    "video/mp4,video/quicktime,video/webm"
)
WORKER_FILES = {"gate_log_photo.png", "dock_camera.mp4", "driver_call.wav"}
SERVER_FILES = {"delivery_receipt.pdf", "pallet_ledger.csv", "witness_email.eml"}


@pytest.fixture
def demo(client, settings, db_session, monkeypatch):
    """The deployed configuration: worker gate on, background work on the test session."""
    settings.external_worker_mimes_raw = WORKER_MIMES
    monkeypatch.setattr(config_module, "get_settings", lambda: settings)

    @contextmanager
    def shared() -> Iterator:
        yield db_session

    client.app.dependency_overrides[get_session_factory] = lambda: shared
    return client


def _load(c):
    res = c.post(URL)
    assert res.status_code == 200, res.text
    return res.json()


def _count(db, model, **where) -> int:
    stmt = select(func.count()).select_from(model)
    for k, v in where.items():
        stmt = stmt.where(getattr(model, k) == v)
    return int(db.scalar(stmt) or 0)


def test_the_bundled_demo_files_are_identical_to_the_sample_evidence():
    for name in DEMO_FILES:
        bundled = (BUNDLED_DEMO_DIR / name).read_bytes()
        original = (REPO_DEMO_DIR / name).read_bytes()
        assert hashlib.sha256(bundled).digest() == hashlib.sha256(original).digest(), name


def test_signing_in_is_required(anon):
    assert anon.post(URL).status_code == 401
    assert anon.get(URL).status_code == 401


def test_a_new_user_loads_the_demo_and_owns_it(demo, db_session):
    assert demo.get(URL).json() == {"case_id": None}
    body = _load(demo)
    case_id = body["case_id"]
    assert body["status"] == "created" and body["title"] == DEMO_TITLE
    assert {f["name"] for f in body["files"]} == set(DEMO_FILES)
    assert demo.get(URL).json() == {"case_id": case_id}

    # In the investigation list, owned by the caller, openable.
    listed = demo.get("/api/cases").json()["items"]
    assert [(c["id"], c["my_role"]) for c in listed if c["id"] == case_id] == [(case_id, "owner")]
    case = demo.get(f"/api/cases/{case_id}").json()
    assert case["title"] == DEMO_TITLE and "Fictional" in case["description"]

    # Evidence metadata and the stored files are available, byte for byte.
    items = demo.get(f"/api/cases/{case_id}/evidence").json()["items"]
    assert {e["original_filename"] for e in items} == set(DEMO_FILES)
    receipt = next(e for e in items if e["original_filename"] == "delivery_receipt.pdf")
    assert receipt["evidence_type"] == "document" and receipt["mime_type"] == "application/pdf"
    data = demo.get(f"/api/cases/{case_id}/evidence/{receipt['id']}/download").content
    assert data == (BUNDLED_DEMO_DIR / "delivery_receipt.pdf").read_bytes()


def test_worker_files_await_the_worker_and_server_files_are_processed(demo, db_session):
    body = _load(demo)
    case_id = body["case_id"]
    by_name = {f["name"]: f for f in body["files"]}
    assert body["queued"] == 3 and body["awaiting_worker"] == 3
    assert {n for n, f in by_name.items() if f["external_worker"]} == WORKER_FILES

    items = {
        e["original_filename"]: e
        for e in demo.get(f"/api/cases/{case_id}/evidence").json()["items"]
    }
    for name in WORKER_FILES:  # never claimed, never marked failed or completed here
        assert items[name]["processing_status"] == "pending", name
        assert items[name]["external_worker"] is True
        assert items[name]["processing_attempts"] == 0
    for name in SERVER_FILES:  # processed by the real extractors in the background task
        assert items[name]["processing_status"] == "completed", (name, items[name])
    summary = demo.get(f"/api/cases/{case_id}/processing").json()["items"]
    assert {i["original_filename"] for i in summary if i["external_worker"]} == WORKER_FILES
    # The background task analysed the case once.
    run = demo.get(f"/api/cases/{case_id}/analysis/latest").json()["run"]
    assert run is not None and run["status"] == "completed"


def test_loading_again_opens_the_same_case_without_duplicates(demo, db_session):
    first = _load(demo)
    second = _load(demo)
    assert second["case_id"] == first["case_id"] and second["status"] == "exists"
    assert second["queued"] == 0  # nothing re-processed
    assert _count(db_session, Case, title=DEMO_TITLE) == 1
    assert _count(db_session, Evidence, case_id=_uuid(first["case_id"])) == len(DEMO_FILES)


def test_a_renamed_demo_case_is_still_recognised(demo, db_session):
    case_id = _load(demo)["case_id"]
    assert demo.patch(f"/api/cases/{case_id}", json={"title": "My copy"}).status_code == 200
    again = _load(demo)
    assert again["case_id"] == case_id and again["title"] == "My copy"


def test_an_interrupted_load_is_completed_on_retry(demo, db_session):
    case_id = _load(demo)["case_id"]
    items = demo.get(f"/api/cases/{case_id}/evidence").json()["items"]
    gone = next(e for e in items if e["original_filename"] == "pallet_ledger.csv")
    assert demo.delete(f"/api/cases/{case_id}/evidence/{gone['id']}").status_code == 204
    again = _load(demo)
    assert again["status"] == "repaired" and again["case_id"] == case_id
    names = [
        e["original_filename"] for e in demo.get(f"/api/cases/{case_id}/evidence").json()["items"]
    ]
    assert sorted(names) == sorted(DEMO_FILES)  # restored once, no duplicates


def test_each_user_gets_a_private_copy(demo, make_user, db_session):
    mine = _load(demo)["case_id"]
    other = make_user("judge@example.org", "Judge")
    assert other.get(f"/api/cases/{mine}").status_code == 404  # existence not revealed
    assert other.get(f"/api/cases/{mine}/evidence").status_code == 404
    assert other.get(URL).json() == {"case_id": None}
    theirs = _load(other)["case_id"]
    assert theirs != mine
    assert [c["id"] for c in other.get("/api/cases").json()["items"]] == [theirs]
    assert demo.get(f"/api/cases/{theirs}").status_code == 404


def test_existing_investigations_are_untouched(demo, db_session):
    existing = demo.post("/api/cases", json={"title": "Real work", "description": "keep"}).json()
    before = demo.get(f"/api/cases/{existing['id']}").json()
    _load(demo)
    after = demo.get(f"/api/cases/{existing['id']}").json()
    assert after == before
    assert demo.get(f"/api/cases/{existing['id']}/evidence").json()["total"] == 0


def test_loading_is_audited_and_the_chain_stays_intact(demo):
    case_id = _load(demo)["case_id"]
    history = demo.get(f"/api/cases/{case_id}/reviews").json()["items"]
    marker = [h for h in history if h["action"] == "demo_case_created"]
    assert (
        len(marker) == 1 and marker[0]["reviewer"] == "Test Investigator <investigator@example.org>"
    )
    chain = demo.get(f"/api/cases/{case_id}/reviews/verify").json()
    assert chain["intact"] is True and chain["checked"] >= 1


def test_owner_permissions_apply_to_the_demo_case(demo, make_user):
    case_id = _load(demo)["case_id"]
    viewer = make_user("viewer@example.org", "Viewer")
    added = demo.post(
        f"/api/cases/{case_id}/members", json={"email": "viewer@example.org", "role": "viewer"}
    )
    assert added.status_code == 201, added.text
    assert viewer.get(f"/api/cases/{case_id}").status_code == 200
    assert viewer.delete(f"/api/cases/{case_id}").status_code == 403
    # A member who is not the owner has no demo case of their own.
    assert viewer.get(URL).json() == {"case_id": None}


def test_missing_demo_files_refuse_cleanly(db_session, settings, storage, tmp_path):
    from app.modules.auth.models import User

    user = User(email="x@example.org", display_name="X", password_hash="x")
    db_session.add(user)
    db_session.flush()
    with pytest.raises(SeedError):
        provision_demo_case(
            db_session,
            EvidenceService(db_session, settings=settings, storage=storage),
            user,
            demo_dir=tmp_path,
        )
    assert _count(db_session, Case, title=DEMO_TITLE) == 0


def _uuid(value: str):
    import uuid

    return uuid.UUID(value)
