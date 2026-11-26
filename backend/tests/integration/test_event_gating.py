"""Event-gated inconsistency detection must not create findings from unrelated events
or from ambiguous associations. All data is synthetic.
"""

from __future__ import annotations

from email.message import EmailMessage

import pytest


def eml(body: str, sender: str = "Ops (fictional) <ops@example.org>") -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "Desk (fictional) <desk@example.org>"
    msg["Subject"] = "Synthetic"
    msg["Date"] = "Mon, 12 Oct 2026 14:00:00 +0000"
    msg.set_content(body)
    return msg.as_bytes()


def scenario(client, *bodies: str) -> dict:
    case_id = client.post("/api/cases", json={"title": "Gating"}).json()["id"]
    for i, body in enumerate(bodies):
        r = client.post(
            f"/api/cases/{case_id}/evidence",
            files={"file": (f"doc{i}.eml", eml(body), "application/octet-stream")},
        )
        assert r.status_code == 201, r.text
        client.post(f"/api/cases/{case_id}/evidence/{r.json()['id']}/process", json={})
    assert client.post(f"/api/cases/{case_id}/analysis").status_code == 202
    run = client.get(f"/api/cases/{case_id}/analysis/latest").json()["run"]
    assert run["status"] == "completed", run
    return {
        "case": case_id,
        "events": client.get(f"/api/cases/{case_id}/events").json()["items"],
        "contradictions": lambda: client.get(f"/api/cases/{case_id}/contradictions").json(),
    }


def confirm_all(client, s) -> None:
    for e in s["events"]:
        r = client.post(
            f"/api/cases/{s['case']}/events/{e['id']}/review", json={"action": "confirm"}
        )
        assert r.status_code == 200, r.text


def test_explicitly_different_vehicles_are_never_grouped_or_compared(client):
    s = scenario(
        client,
        "Gate log: truck KX-4471 arrived at 10:30 on 12 October 2026.",
        "Witness statement: truck MH-1234 arrived at 12:15 on 12 October 2026.",
    )
    # The shared word "truck" must not join two explicitly different plates.
    assert s["events"] == [], s["events"]
    assert s["contradictions"]()["total"] == 0


def test_different_kinds_of_event_are_not_compared(client):
    s = scenario(
        client,
        "Gate log: truck KX-4471 arrived at 10:30 on 12 October 2026.",
        "Driver log: truck KX-4471 departed at 12:15 on 12 October 2026.",
    )
    # One arrival and one departure are two different events, each with one account:
    # nothing is proposed, and arrival/departure times are never compared.
    assert s["events"] == []
    confirm_all(client, s)
    # Arriving at 10:30 and leaving at 12:15 is the usual order: nothing to flag.
    assert s["contradictions"]()["total"] == 0


AMBIGUOUS = (
    # Linked only by the word "truck": possibly the same truck, possibly not.
    "Gate log: the truck arrived at 10:30 on 12 October 2026.",
    "Witness statement: a truck arrived at 12:15 on 12 October 2026.",
)


def test_an_ambiguous_proposal_alone_never_creates_a_finding(client):
    s = scenario(client, *AMBIGUOUS)
    (event,) = s["events"]
    assert event["status"] == "proposed" and event["anchor_kind"] == "object"
    assert event["association_confidence"] < 0.5
    assert any(c["is_candidate"] for c in event["comparisons"])
    assert s["contradictions"]()["total"] == 0  # proposed, not confirmed


def test_rejected_association_creates_no_finding(client):
    s = scenario(client, *AMBIGUOUS)
    (event,) = s["events"]
    url = f"/api/cases/{s['case']}/events/{event['id']}/review"
    assert client.post(url, json={"action": "reject", "note": "two visits"}).status_code == 200
    assert s["contradictions"]()["total"] == 0


def test_shared_exact_identifier_is_compared_without_an_event_and_never_twice(client):
    """Phase 1 behaviour is kept: an exact shared plate/identifier is a strong link, so
    those accounts are compared directly. Confirming the event adds no duplicate."""
    s = scenario(
        client,
        "Gate log: truck KX-4471 arrived at 10:30 on 12 October 2026.",
        "Witness statement: truck KX-4471 arrived at 12:15 on 12 October 2026.",
    )
    (event,) = s["events"]
    assert event["anchor_kind"] in ("identifier", "vehicle")
    (c,) = s["contradictions"]()["items"]
    assert c["via_entity_id"] and c["via_event_id"] is None
    confirm_all(client, s)
    assert s["contradictions"]()["total"] == 1


def test_confirmed_event_flags_only_real_time_differences(client):
    s = scenario(
        client,
        "Gate log: the truck arrived at 10:30 on 12 October 2026.",
        "Delivery receipt: the truck arrived at 10:34 on 12 October 2026.",
        "Witness statement: a truck arrived at 12:15 on 12 October 2026.",
    )
    (event,) = s["events"]
    assert s["contradictions"]()["total"] == 0
    confirm_all(client, s)
    items = s["contradictions"]()["items"]
    # gate vs receipt (4 min) is within tolerance; only the witness differs.
    assert len(items) == 2
    for c in items:
        quotes = {c["claim_a"]["quote"], c["claim_b"]["quote"]}
        assert any("12:15" in q for q in quotes)
        assert c["via_event_id"] == event["id"]
        assert c["alternatives"], "every finding offers benign explanations"
        assert 0 < c["detection_confidence"] < 1


@pytest.mark.parametrize(
    ("a", "b"),
    [
        # different stated days
        (
            "Gate log: truck KX-4471 arrived at 10:30 on 12 October 2026.",
            "Witness statement: truck KX-4471 arrived at 12:15 on 13 October 2026.",
        ),
        # one account gives no time at all
        (
            "Gate log: truck KX-4471 arrived at 10:30 on 12 October 2026.",
            "Witness statement: truck KX-4471 arrived on 12 October 2026.",
        ),
    ],
    ids=["different-day", "missing-time"],
)
def test_confirmed_but_not_comparable_accounts_create_no_finding(client, a, b):
    s = scenario(client, a, b)
    confirm_all(client, s)
    assert s["contradictions"]()["total"] == 0


def test_planned_and_actual_times_are_not_contradictions(client):
    s = scenario(
        client,
        "Schedule: truck KX-4471 was expected to arrive at 09:00 on 12 October 2026.",
        "Gate log: truck KX-4471 arrived at 11:40 on 12 October 2026.",
    )
    # Planned and actual arrivals are different event types: never grouped together.
    assert s["events"] == [], s["events"]
    assert s["contradictions"]()["total"] == 0
