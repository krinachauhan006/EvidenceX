"""Integration tests for the cases HTTP API against a real database."""

from __future__ import annotations

import uuid


def _create(client, title="Case One", description=None):
    return client.post("/api/cases", json={"title": title, "description": description})


# --- health ---------------------------------------------------------------------


def test_health_ok(client):
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["service"] == "evidencex-api"
    assert body["status"] in {"ok", "degraded"}


# --- create ---------------------------------------------------------------------


def test_create_case_happy_path(client):
    res = _create(client, "Operation Nightfall", "initial notes")
    assert res.status_code == 201
    body = res.json()
    assert body["title"] == "Operation Nightfall"
    assert body["status"] == "open"
    assert uuid.UUID(body["id"])  # valid UUID
    assert body["created_at"] and body["updated_at"]


def test_create_empty_title_rejected(client):
    res = _create(client, "   ")
    assert res.status_code == 422


def test_create_long_title_rejected(client):
    res = _create(client, "x" * 201)
    assert res.status_code == 422


# --- list -----------------------------------------------------------------------


def test_list_empty_returns_empty_list(client):
    res = client.get("/api/cases")
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_list_orders_by_updated_at_desc_and_paginates(client):
    first = _create(client, "First").json()
    second = _create(client, "Second").json()

    res = client.get("/api/cases", params={"limit": 1, "offset": 0})
    body = res.json()
    assert body["total"] == 2
    assert body["limit"] == 1
    assert len(body["items"]) == 1
    # Most recently updated first.
    assert body["items"][0]["id"] == second["id"]

    res2 = client.get("/api/cases", params={"limit": 1, "offset": 1})
    assert res2.json()["items"][0]["id"] == first["id"]


# --- get ------------------------------------------------------------------------


def test_get_found(client):
    created = _create(client).json()
    res = client.get(f"/api/cases/{created['id']}")
    assert res.status_code == 200
    assert res.json()["id"] == created["id"]


def test_get_missing_returns_404(client):
    res = client.get(f"/api/cases/{uuid.uuid4()}")
    assert res.status_code == 404


def test_get_malformed_id_returns_422(client):
    res = client.get("/api/cases/not-a-uuid")
    assert res.status_code == 422


# --- update ---------------------------------------------------------------------


def test_update_case(client):
    created = _create(client, "Old").json()
    res = client.patch(
        f"/api/cases/{created['id']}",
        json={"title": "New", "description": "changed"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "New"
    assert body["description"] == "changed"


def test_update_invalid_status_returns_422(client):
    created = _create(client).json()
    res = client.patch(f"/api/cases/{created['id']}", json={"status": "deleted"})
    assert res.status_code == 422


def test_update_missing_returns_404(client):
    res = client.patch(f"/api/cases/{uuid.uuid4()}", json={"title": "x"})
    assert res.status_code == 404


# --- archive --------------------------------------------------------------------


def test_archive_hides_from_default_list_but_preserves_data(client):
    created = _create(client, "Archive Me", "keep this").json()

    res = client.post(f"/api/cases/{created['id']}/archive")
    assert res.status_code == 200
    assert res.json()["status"] == "archived"

    # Default list excludes it.
    default = client.get("/api/cases").json()
    assert all(c["id"] != created["id"] for c in default["items"])

    # Still retrievable directly with all data intact.
    fetched = client.get(f"/api/cases/{created['id']}").json()
    assert fetched["description"] == "keep this"

    # Visible via explicit archived filter.
    archived = client.get("/api/cases", params={"status": "archived"}).json()
    assert any(c["id"] == created["id"] for c in archived["items"])


def test_archive_missing_returns_404(client):
    res = client.post(f"/api/cases/{uuid.uuid4()}/archive")
    assert res.status_code == 404


# --- delete ---------------------------------------------------------------------


def test_delete_returns_204_and_removes_case(client):
    created = _create(client, "Delete Me").json()
    res = client.delete(f"/api/cases/{created['id']}")
    assert res.status_code == 204
    assert client.get(f"/api/cases/{created['id']}").status_code == 404


def test_delete_missing_returns_404(client):
    res = client.delete(f"/api/cases/{uuid.uuid4()}")
    assert res.status_code == 404


def test_delete_is_scoped_and_does_not_affect_other_cases(client):
    a = _create(client, "Case A").json()
    b = _create(client, "Case B").json()

    assert client.delete(f"/api/cases/{a['id']}").status_code == 204

    # Unrelated case B is untouched.
    assert client.get(f"/api/cases/{b['id']}").status_code == 200
