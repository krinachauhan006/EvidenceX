"""Small API helpers shared by the failure/recovery tests."""

from __future__ import annotations

import uuid
from typing import Any

SEGMENT_CONTENT_KEYS = (
    "seq",
    "segment_type",
    "text",
    "data",
    "locator",
    "page",
    "t_start",
    "t_end",
    "engine_confidence",
    "language",
)


def unique_csv(rows: int = 3) -> bytes:
    """A CSV whose content (and therefore SHA-256) is unique to each call.

    One header plus ``rows`` data rows, so a completed run has ``rows + 1`` segments.
    """
    lines = ["id,note"]
    lines += [f"{i},row-{i}" for i in range(1, rows)]
    lines.append(f"{rows},unique-{uuid.uuid4()}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def make_case(client, title: str = "Recovery case") -> str:
    res = client.post("/api/cases", json={"title": title, "description": None})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def upload(client, case_id: str, data: bytes, name: str = "ledger.csv") -> dict[str, Any]:
    res = client.post(
        f"/api/cases/{case_id}/evidence",
        files={"file": (name, data, "text/csv")},
    )
    assert res.status_code == 201, res.text
    return res.json()


def _base(case_id: str, evidence_id: str) -> str:
    return f"/api/cases/{case_id}/evidence/{evidence_id}"


def process(client, case_id: str, evidence_id: str, *, force: bool = False):
    return client.post(f"{_base(case_id, evidence_id)}/process", json={"force": force})


def retry(client, case_id: str, evidence_id: str):
    return client.post(f"{_base(case_id, evidence_id)}/retry")


def status(client, case_id: str, evidence_id: str) -> dict[str, Any]:
    res = client.get(f"{_base(case_id, evidence_id)}/processing")
    assert res.status_code == 200, res.text
    return res.json()


def evidence_row(client, case_id: str, evidence_id: str) -> dict[str, Any]:
    """The evidence metadata the UI list shows (status, error text and code)."""
    res = client.get(_base(case_id, evidence_id))
    assert res.status_code == 200, res.text
    return res.json()


def summary(client, case_id: str) -> dict[str, Any]:
    res = client.get(f"/api/cases/{case_id}/processing")
    assert res.status_code == 200, res.text
    return res.json()


def summary_item(client, case_id: str, evidence_id: str) -> dict[str, Any]:
    (item,) = [i for i in summary(client, case_id)["items"] if i["evidence_id"] == evidence_id]
    return item


def runs(client, case_id: str, evidence_id: str) -> list[dict[str, Any]]:
    """Run history, newest first."""
    res = client.get(f"{_base(case_id, evidence_id)}/extractions")
    assert res.status_code == 200, res.text
    return res.json()["items"]


def digest(run_list: list[dict[str, Any]]) -> list[tuple[int, str, bool]]:
    """(run_number, run_status, is_current), oldest first, for compact assertions."""
    return [(r["run_number"], r["run_status"], r["is_current"]) for r in reversed(run_list)]


def segments_response(client, case_id: str, evidence_id: str, extraction_id: str | None = None):
    params: dict[str, Any] = {"limit": 500}
    if extraction_id is not None:
        params["extraction_id"] = extraction_id
    return client.get(f"{_base(case_id, evidence_id)}/segments", params=params)


def segments(
    client, case_id: str, evidence_id: str, extraction_id: str | None = None
) -> list[dict[str, Any]]:
    """Segments of a run (the current run when ``extraction_id`` is omitted)."""
    res = segments_response(client, case_id, evidence_id, extraction_id)
    assert res.status_code == 200, res.text
    return res.json()["items"]


def content_of(segment_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Segment content without ids, to compare the same content across runs."""
    return [{k: s[k] for k in SEGMENT_CONTENT_KEYS} for s in segment_list]
