"""Phase 2 through the API: events, event-gated inconsistencies, timeline, search,
grounded Q&A, reports (real PDF content checks), graph exports and the audit chain.

All data here is synthetic. AI is never called: the Gemini transport is faked.
"""

from __future__ import annotations

import json
import re
import unicodedata
from email.message import EmailMessage

import pymupdf
import pytest

from app.ai.gemini_client import GeminiClient
from app.modules.analysis import phase2_service
from app.modules.analysis.models import ReviewAction
from app.modules.analysis.report_text import BANNED

RECEIPT = "Delivery receipt: Truck arrived 10:30 on 12 October 2026."
WITNESS = "Witness statement: Truck arrived 12:15 on 12 October 2026."
GATE = "The gate log shows the truck arrived at 10:32 on 12 October 2026."


def eml(body: str, subject: str = "Synthetic test message") -> bytes:
    msg = EmailMessage()
    msg["From"] = "Ops (fictional) <ops@example.org>"
    msg["To"] = "Desk (fictional) <desk@example.org>"
    msg["Subject"] = subject
    msg["Date"] = "Mon, 12 Oct 2026 14:00:00 +0000"
    msg["Message-ID"] = "<test@example.org>"
    msg.set_content(body)
    return msg.as_bytes()


def make_case(client, title="Phase 2 case") -> str:
    return client.post("/api/cases", json={"title": title, "description": "Synthetic"}).json()["id"]


def add(client, case_id, name, data) -> str:
    r = client.post(
        f"/api/cases/{case_id}/evidence", files={"file": (name, data, "application/octet-stream")}
    )
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    assert client.post(f"/api/cases/{case_id}/evidence/{eid}/process", json={}).status_code == 202
    return eid


def analyse(client, case_id) -> dict:
    assert client.post(f"/api/cases/{case_id}/analysis").status_code == 202
    run = client.get(f"/api/cases/{case_id}/analysis/latest").json()["run"]
    assert run["status"] == "completed", run
    return run


@pytest.fixture
def truck(client):
    case_id = make_case(client)
    add(client, case_id, "accounts.eml", eml(f"{RECEIPT}\n{WITNESS}\n"))
    add(client, case_id, "gate.eml", eml(GATE))
    run = analyse(client, case_id)
    events = client.get(f"/api/cases/{case_id}/events").json()["items"]
    return {"case": case_id, "run": run, "events": events}


def test_event_is_proposed_with_reasons_not_assumed(client, truck):
    assert truck["run"]["stats"]["events_proposed"] >= 1
    (event,) = [e for e in truck["events"] if e["event_type"] == "arrival"]
    assert event["status"] == "proposed" and event["anchor_kind"] == "object"
    assert event["event_date"] == "2026-10-12" and event["link_basis"] == "context"
    labels = sorted(m["account_label"] for m in event["members"])
    assert labels == [
        "accounts.eml — delivery receipt",
        "accounts.eml — witness statement",
        "gate.eml — gate log",
    ]
    assert any("no shared identifier" in m for m in event["missing_links"])
    assert 0 < event["association_confidence"] < 0.6  # object-word link is weak
    kinds = {
        frozenset((c["account_a"], c["account_b"])): c["classification"]
        for c in event["comparisons"]
    }
    assert (
        kinds[frozenset(("accounts.eml — delivery receipt", "gate.eml — gate log"))]
        == "within_tolerance"
    )
    assert (
        kinds[frozenset(("accounts.eml — delivery receipt", "accounts.eml — witness statement"))]
        == "conflict_candidate"
    )
    # A proposal never creates a potential inconsistency on its own.
    assert client.get(f"/api/cases/{truck['case']}/contradictions").json()["total"] == 0


def test_confirming_the_event_compares_accounts_including_same_document(client, truck):
    case_id = truck["case"]
    (event,) = [e for e in truck["events"] if e["event_type"] == "arrival"]
    url = f"/api/cases/{case_id}/events/{event['id']}/review"
    r = client.post(url, json={"action": "confirm", "note": "same delivery"})
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    cons = client.get(f"/api/cases/{case_id}/contradictions").json()["items"]
    assert len(cons) == 2  # receipt vs witness, witness vs gate log; not receipt vs gate
    same_doc = [c for c in cons if c["claim_a"]["evidence_name"] == c["claim_b"]["evidence_name"]]
    assert len(same_doc) == 1
    c = same_doc[0]
    assert c["via_event_id"] == event["id"] and c["via_event_status"] == "confirmed"
    assert c["explanation"]["classification"] == "conflict_candidate"
    assert any(
        f["factor"].startswith("linked by reviewer-confirmed event")
        for f in c["explanation"]["factors"]
    )
    assert "different occurrences" in c["alternatives"][0]["explanation"]
    assert any("same document" in u for u in c["uncertainty"])
    assert client.post(url, json={"action": "confirm"}).status_code == 409
    # Rejecting later keeps the records, labelled.
    client.post(url, json={"action": "reject", "note": "two trucks after all"})
    cons2 = client.get(f"/api/cases/{case_id}/contradictions").json()["items"]
    assert len(cons2) == 2 and all(x["via_event_status"] == "rejected" for x in cons2)


def test_event_split_and_regroup_are_audited(client, truck):
    case_id = truck["case"]
    (event,) = [e for e in truck["events"] if e["event_type"] == "arrival"]
    url = f"/api/cases/{case_id}/events/{event['id']}/review"
    gate = next(m for m in event["members"] if "gate" in m["account_label"])
    r = client.post(url, json={"action": "split", "claim_ids": [gate["claim"]["id"]]})
    assert r.status_code == 200 and len(r.json()["members"]) == 2
    all_ids = [m["claim"]["id"] for m in event["members"]]
    assert client.post(url, json={"action": "split", "claim_ids": all_ids}).status_code == 400
    r = client.post(url, json={"action": "add_claim", "claim_id": gate["claim"]["id"]})
    assert r.status_code == 200 and len(r.json()["members"]) == 3
    actions = [
        h["action"]
        for h in client.get(f"/api/cases/{case_id}/events/{event['id']}").json()["history"]
    ]
    assert {"split", "add_claim"} <= set(actions)
    verify = client.get(f"/api/cases/{case_id}/reviews/verify").json()
    assert verify["intact"] is True and verify["checked"] >= 2


def test_different_days_are_never_compared(client):
    case_id = make_case(client, "Two days")
    add(client, case_id, "a.eml", eml("Delivery receipt: Truck arrived 10:30 on 12 October 2026."))
    add(client, case_id, "b.eml", eml("Witness statement: Truck arrived 15:00 on 13 October 2026."))
    analyse(client, case_id)
    events = client.get(f"/api/cases/{case_id}/events").json()["items"]
    assert all(len(e["members"]) < 2 or e["event_date"] for e in events)
    assert not [e for e in events if e["event_type"] == "arrival"]  # split by date: no group


def test_reviewer_roles_on_events(client, truck, make_user):
    case_id = truck["case"]
    viewer = make_user("v@example.org", "V")
    client.post(f"/api/cases/{case_id}/members", json={"email": "v@example.org", "role": "viewer"})
    (event,) = [e for e in truck["events"] if e["event_type"] == "arrival"]
    r = viewer.post(f"/api/cases/{case_id}/events/{event['id']}/review", json={"action": "confirm"})
    assert r.status_code == 403
    assert viewer.get(f"/api/cases/{case_id}/timeline").status_code == 200


def test_timeline_orders_by_date_and_time(client, truck):
    tl = client.get(f"/api/cases/{truck['case']}/timeline").json()
    (day,) = [g for g in tl["groups"] if g["date"] == "2026-10-12"]
    timed = [i for i in day["items"] if i["start_minute"] is not None]
    minutes = [i["start_minute"] for i in timed]
    assert minutes == sorted(minutes) and minutes[:3] == [630, 632, 735]
    assert all(i["events"] for i in timed)
    # Date-only statements (no time) come after the timed ones on the same day.
    assert [i["start_minute"] for i in day["items"]][: len(timed)] == minutes
    assert "never placed on a guessed day" in tl["undated_note"]


def test_search_keyword_synonym_typo_and_isolation(client, truck):
    case_id = truck["case"]
    hits = client.get(f"/api/cases/{case_id}/search", params={"q": "lorry arrival"}).json()
    assert hits["items"] and "Not embedding-based" in hits["method"]
    top = next(h for h in hits["items"] if h["kind"] in ("claim", "segment"))
    assert top["evidence_name"] and top["locator"]  # source hits carry exact citations
    assert "synonym" in " ".join(h["why"] for h in hits["items"])
    typo = client.get(f"/api/cases/{case_id}/search", params={"q": "witnes statment"}).json()
    assert any("Witness statement" in h["excerpt"] for h in typo["items"])
    other = make_case(client, "Unrelated")
    assert client.get(f"/api/cases/{other}/search", params={"q": "truck"}).json()["total"] == 0


def test_ask_without_ai_is_retrieval_only(client, truck):
    r = client.post(
        f"/api/cases/{truck['case']}/ask", json={"question": "When did the truck arrive?"}
    ).json()
    assert r["method"] == "retrieval only (no AI)"
    assert r["citations"] and all(s["citations"] for s in r["answer"])
    assert "did not interpret" in r["notice"]


class FakeTransport:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __call__(self, url, body, headers, timeout):
        self.calls.append(json.loads(body))
        text = json.dumps(self.payload)
        return json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]}).encode()


def test_ask_with_fake_ai_drops_uncited_and_adjudicating_statements(client, truck, monkeypatch):
    transport = FakeTransport(
        {
            "statements": [
                {"text": "The receipt says 10:30.", "citations": ["S1"], "support": "supported"},
                {"text": "Made up claim.", "citations": ["S99"], "support": "supported"},
                {"text": "The witness lied.", "citations": ["S1"], "support": "interpretation"},
            ]
        }
    )
    fake = GeminiClient(api_key="k", model="gemini-test", transport=transport)
    monkeypatch.setattr(phase2_service, "_ai_client", lambda settings, case: fake)
    r = client.post(
        f"/api/cases/{truck['case']}/ask", json={"question": "When did the truck arrive?"}
    ).json()
    assert r["method"].startswith("gemini") and r["removed_unsupported"] == 2
    assert [s["text"] for s in r["answer"]] == ["The receipt says 10:30."]
    sent = transport.calls[0]["contents"][0]["parts"][0]["text"]
    assert (
        "<sources>" in sent
        and "UNTRUSTED DATA" in transport.calls[0]["systemInstruction"]["parts"][0]["text"]
    )


def test_ai_client_requires_case_consent(client):
    from app.core.config import Settings
    from app.modules.cases.models import Case

    s = Settings(CLAIM_EXTRACTOR="hybrid", GEMINI_API_KEY="secret")
    assert phase2_service._ai_client(s, Case(title="x", ai_processing_allowed=False)) is None
    assert phase2_service._ai_client(s, Case(title="x", ai_processing_allowed=True)) is not None
    off = Settings(CLAIM_EXTRACTOR="rule_based", GEMINI_API_KEY="secret")
    assert phase2_service._ai_client(off, Case(title="x", ai_processing_allowed=True)) is None


def _pdf_text(data: bytes) -> tuple[int, str]:
    doc = pymupdf.open("pdf", data)
    text = " ".join(" ".join(p.get_text().split()) for p in doc)  # undo line wrapping
    # The PDF font renders "fi"/"ff"/"fl" as ligature glyphs; NFKC maps them back so
    # phrase checks (and the banned-wording check) see the plain words.
    return doc.page_count, unicodedata.normalize("NFKC", text)


def test_investigation_report_pdf_content(client, truck):
    case_id = truck["case"]
    (event,) = [e for e in truck["events"] if e["event_type"] == "arrival"]
    client.post(f"/api/cases/{case_id}/events/{event['id']}/review", json={"action": "confirm"})
    r = client.post(f"/api/cases/{case_id}/reports", json={"kind": "investigation"})
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["version"] == 1 and rep["page_count"] >= 3
    pdf = client.get(f"/api/cases/{case_id}/reports/{rep['id']}/download")
    assert pdf.headers["content-type"] == "application/pdf"
    assert "attachment" in pdf.headers["content-disposition"]
    pages, text = _pdf_text(pdf.content)
    assert pages == rep["page_count"]
    for needle in [
        "Executive summary",
        "Phase 2 case",
        "Truck arrived 10:30",
        "email body (plain text)",
        "Possible inconsistencies",
        "What cannot be determined",
        "does not determine",
        f"Page 1 of {pages}",
        "Alternative explanations",
        # narrative structure: claims with sources, conflict split, references, disclaimer
        "Key claims and their sources",
        "Conflicting accounts",
        "Source references",
        "Limitations and disclaimer",
        "[1] ",
    ]:
        assert needle in text, needle
    # Every evidence item is listed with its FULL hash in the references.
    for e in client.get(f"/api/cases/{case_id}/evidence").json()["items"]:
        assert e["sha256"] in text.replace(" ", "")
    # Outside verbatim evidence quotes, the report never adjudicates.
    generated = re.sub(r"“[^”]*”", "", text)
    assert not BANNED.search(generated), BANNED.search(generated)
    again = client.post(f"/api/cases/{case_id}/reports", json={"kind": "investigation"}).json()
    assert again["version"] == 2
    listed = client.get(f"/api/cases/{case_id}/reports").json()
    assert listed["total"] == 2


def test_report_for_unanalysed_case_states_no_findings(client):
    case_id = make_case(client, "Empty case")
    rep = client.post(f"/api/cases/{case_id}/reports", json={"kind": "investigation"}).json()
    _, text = _pdf_text(client.get(f"/api/cases/{case_id}/reports/{rep['id']}/download").content)
    assert "has not been analysed yet" in text and "No findings can be reported" in text


def test_report_handles_multilingual_text(client):
    case_id = make_case(client, "Café Ünïcode — Сыск")
    add(
        client,
        case_id,
        "m.eml",
        eml("Delivery receipt: Truck arrived 09:00 on 1 May 2026. Примечание: груз прибыл."),
    )
    analyse(client, case_id)
    rep = client.post(f"/api/cases/{case_id}/reports", json={"kind": "investigation"}).json()
    _, text = _pdf_text(client.get(f"/api/cases/{case_id}/reports/{rep['id']}/download").content)
    assert "Café Ünïcode" in text and "Сыск" in text


def test_graph_exports(client, truck):
    case_id = truck["case"]
    g = client.get(f"/api/cases/{case_id}/graph").json()
    assert any(n["kind"] == "event" for n in g["nodes"])
    assert any(e["kind"] == "account_of" for e in g["edges"])
    j = client.get(f"/api/cases/{case_id}/graph/export", params={"format": "json"})
    body = json.loads(j.content)
    assert body["format"] == "evidencex-graph/1" and body["nodes"]
    gm = client.get(f"/api/cases/{case_id}/graph/export", params={"format": "graphml"})
    assert b"<graphml" in gm.content
    rep = client.post(f"/api/cases/{case_id}/reports", json={"kind": "graph"}).json()
    pages, text = _pdf_text(
        client.get(f"/api/cases/{case_id}/reports/{rep['id']}/download").content
    )
    assert pages >= 3 and "Legend" in text and "Important connections" in text
    assert "not verified facts" in text or "not independently verified facts" in text


def test_generated_pdfs_keep_the_pymupdf_producer_and_licence_notices(client, truck):
    # Artifex's AGPL guidance: keep the copyright and producer metadata in generated PDFs.
    case_id = truck["case"]
    for kind in ("investigation", "graph"):
        rep = client.post(f"/api/cases/{case_id}/reports", json={"kind": kind}).json()
        data = client.get(f"/api/cases/{case_id}/reports/{rep['id']}/download").content
        meta = pymupdf.open("pdf", data).metadata
        assert meta["producer"].startswith(f"PyMuPDF {pymupdf.VersionBind}"), meta
        assert f"MuPDF {pymupdf.VersionFitz}" in meta["producer"]
        assert "Artifex Software, Inc." in meta["producer"] and "AGPL-3.0" in meta["producer"]
        assert meta["creator"].startswith("EvidenceX (GNU AGPL-3.0)"), meta
        assert "https://github.com/krinachauhan006/EvidenceX" in meta["creator"]
        assert meta["title"]  # the document title is still set


def test_audit_chain_detects_tampering(client, truck, db_session):
    case_id = truck["case"]
    (event,) = [e for e in truck["events"] if e["event_type"] == "arrival"]
    client.post(
        f"/api/cases/{case_id}/events/{event['id']}/review",
        json={"action": "note", "note": "original"},
    )
    assert client.get(f"/api/cases/{case_id}/reviews/verify").json()["intact"]
    row = db_session.query(ReviewAction).filter(ReviewAction.note == "original").one()
    row.note = "edited later"
    db_session.flush()
    broken = client.get(f"/api/cases/{case_id}/reviews/verify").json()
    assert broken["intact"] is False and broken["broken_at"] == str(row.id)


def test_ai_status_never_exposes_the_key(client, monkeypatch):
    from app.core.config import Settings
    from app.modules.analysis import router_phase2

    fake = Settings(CLAIM_EXTRACTOR="hybrid", GEMINI_API_KEY="sk-test-never-shown-123")
    monkeypatch.setattr(router_phase2, "get_settings", lambda: fake)
    r = client.get("/api/ai/status")
    s = r.json()
    assert s["key_configured"] is True and s["available"] is True
    assert "sk-test-never-shown-123" not in r.text
    assert s["consent_required"] is True


def _mail_from(sender: str, body: str) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "Desk (fictional) <desk@example.org>"
    msg["Subject"] = "Synthetic"
    msg["Date"] = "Mon, 12 Oct 2026 14:00:00 +0000"
    msg.set_content(body)
    return msg.as_bytes()


def test_entity_candidates_are_tiered_and_can_be_deferred(client):
    case_id = make_case(client, "Entity tiers")
    add(client, case_id, "a.eml", _mail_from("Ravi Kumar <ravi@example.org>", "Shipment NS88421."))
    add(client, case_id, "b.eml", _mail_from("Ravi Kumar <rk@example.net>", "Parcel 88421 noted."))
    analyse(client, case_id)
    items = client.get(f"/api/cases/{case_id}/entities/candidates").json()["items"]
    tiers = {c["tier"] for c in items}
    assert "conflicting" in tiers, items
    pair = next(c for c in items if c["tier"] == "conflicting")
    assert pair["score_kind"] == "heuristic" and pair["deferred"] is False
    assert {f["effect"] for f in pair["factors"]} == {"+", "-"}
    a, b = pair["entity_a"]["id"], pair["entity_b"]["id"]
    url = f"/api/cases/{case_id}/entities/{a}/review"
    # Deferring needs a note and changes no status.
    assert client.post(url, json={"action": "defer", "target_entity_id": b}).status_code == 400
    r = client.post(url, json={"action": "defer", "target_entity_id": b, "note": "ask the desk"})
    assert r.status_code == 200, r.text
    assert r.json()["resolution_status"] == "unresolved"
    again = client.get(f"/api/cases/{case_id}/entities/candidates").json()["items"]
    kept = next(c for c in again if {c["entity_a"]["id"], c["entity_b"]["id"]} == {a, b})
    assert kept["deferred"] is True and kept["deferred_note"] == "ask the desk"
    assert "defer" in [h["action"] for h in r.json()["history"]]
    # Marking them distinct removes the pair; nothing was merged automatically.
    client.post(url, json={"action": "mark_distinct", "target_entity_id": b})
    final = client.get(f"/api/cases/{case_id}/entities/candidates").json()["items"]
    assert not [c for c in final if {c["entity_a"]["id"], c["entity_b"]["id"]} == {a, b}]
    ents = client.get(f"/api/cases/{case_id}/entities").json()["items"]
    assert all(e["resolution_status"] != "merged" for e in ents)
