"""Investigation report: consistent snapshot -> neutral narrative HTML -> paginated PDF.

The snapshot is read once, before any text is written, so every finding and
citation in one report comes from the same state of the case. All narrative sentences
are built from stored records only; evidence text appears verbatim inside quotation
marks and is HTML-escaped. Generated wording passes ``report_text.guard``.

PDF layout uses PyMuPDF's Story (HTML + CSS -> pages), which is already a project
dependency for PDF extraction. Page numbers, running header and PDF bookmarks are
added in a second pass.
"""

from __future__ import annotations

import io
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.analysis.audit import verify_chain
from app.modules.analysis.report_text import (
    DISCLAIMER,
    cite,
    esc,
    guard,
    plural,
)

REPORT_CSS = """
* { font-family: sans-serif; }
body { font-size: 10pt; color: #1b2433; line-height: 1.38; }
h1 { font-size: 22pt; color: #0e1a2e; margin: 0 0 6pt 0; }
h2 { font-size: 14pt; color: #0e1a2e; margin: 16pt 0 6pt 0; padding-bottom: 3pt;
     border-bottom: 1px solid #b9c2d0; }
h3 { font-size: 11pt; color: #1f2f4a; margin: 10pt 0 4pt 0; }
p { margin: 0 0 6pt 0; }
.muted { color: #5b6577; font-size: 9pt; }
.cover-kicker { color: #9a6a00; font-size: 9pt; letter-spacing: 1pt; }
.box { border: 1px solid #c9d1dc; background-color: #f5f7fa; padding: 6pt; margin: 6pt 0; }
.warn { border: 1px solid #e0b25a; background-color: #fff7e6; padding: 6pt; margin: 6pt 0; }
.quote { font-family: monospace; font-size: 9pt; color: #1b2433; background-color: #f2f4f7;
         padding: 3pt; margin: 2pt 0 4pt 0; }
.cite { color: #2b5a8a; font-size: 8.5pt; }
table { border-collapse: collapse; width: 100%; margin: 4pt 0 8pt 0; }
th { background-color: #e7ebf1; color: #0e1a2e; font-size: 8.5pt; text-align: left;
     padding: 3pt; border: 1px solid #c9d1dc; }
td { font-size: 8.5pt; padding: 3pt; border: 1px solid #d9dee6; vertical-align: top; }
.tag { font-size: 8pt; color: #5b6577; }
"""


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


# --- snapshot -----------------------------------------------------------------------


def build_snapshot(db: Session, case_id: uuid.UUID) -> dict[str, Any]:
    """Everything the report needs, read once."""
    from app.modules.analysis.event_service import EventService
    from app.modules.analysis.repository import AnalysisRepository
    from app.modules.analysis.service import AnalysisService
    from app.modules.cases.models import Case

    service = AnalysisService(db)
    repo = AnalysisRepository(db)
    case = db.get(Case, case_id)
    evidence = repo.list_evidence(case_id)
    run = repo.latest_run(case_id)
    claims = service.list_claims(
        case_id,
        evidence_id=None,
        review_status=None,
        claim_type=None,
        modality=None,
        entity_id=None,
        segment_id=None,
        search=None,
        include_superseded=False,
        limit=500,
        offset=0,
    ).items
    contradictions = service.list_contradictions(
        case_id, review_status=None, severity=None, evidence_id=None, entity_id=None
    ).items
    events = EventService(db).list_events(case_id).items
    timeline = EventService(db).timeline(case_id)
    entities = service.list_entities(
        case_id, entity_type=None, search=None, include_merged=False
    ).items
    reviews = service.reviews(case_id, target_type=None, target_id=None, limit=500).items
    chain = verify_chain(db, case_id)
    return {
        "case": {
            "id": str(case.id),
            "title": case.title,
            "description": case.description,
            "status": case.status,
            "ai_processing_allowed": case.ai_processing_allowed,
        },
        "generated_at": _now(),
        "run": {
            "id": str(run.id),
            "method": run.method,
            "status": run.status,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "stats": dict(run.stats or {}),
        }
        if run
        else None,
        "evidence": [
            {
                "id": str(e.id),
                "name": e.original_filename,
                "type": e.evidence_type,
                "mime": e.mime_type,
                "bytes": e.byte_size,
                "sha256": e.sha256,
                "status": e.processing_status,
                "error": e.processing_error,
            }
            for e in evidence
        ],
        "claims": [c.model_dump(mode="json") for c in claims],
        "contradictions": [c.model_dump(mode="json") for c in contradictions],
        "events": [e.model_dump(mode="json") for e in events],
        "timeline": timeline.model_dump(mode="json"),
        "entities": [e.model_dump(mode="json") for e in entities],
        "reviews": [r.model_dump(mode="json") for r in reviews],
        "audit_chain": chain,
    }


def snapshot_index(snap: dict[str, Any]) -> dict[str, Any]:
    """The ids and states a report was built from (stored with the report)."""
    return {
        "run_id": (snap.get("run") or {}).get("id"),
        "evidence": [e["id"] for e in snap["evidence"]],
        "claims": {c["id"]: c["review_status"] for c in snap["claims"]},
        "contradictions": {c["id"]: c["review_status"] for c in snap["contradictions"]},
        "events": {e["id"]: e["status"] for e in snap["events"]},
        "audit_head": snap["audit_chain"].get("head"),
    }


# --- narrative ----------------------------------------------------------------------

TYPE_LABEL = {
    "document": "PDF document",
    "image": "image",
    "audio": "audio recording",
    "tabular": "spreadsheet/table",
    "email": "email",
    "video": "video",
}
STATUS_LABEL = {
    "unreviewed": "awaiting review",
    "confirmed": "confirmed by a reviewer",
    "rejected": "rejected by a reviewer",
    "unresolved": "marked unresolved",
    "resolved": "resolved by a reviewer",
    "proposed": "proposed (not reviewed)",
    "verified": "verified by a reviewer",
    "needs_verification": "needs verification",
}


def _claim_line(c: dict[str, Any]) -> str:
    method = "rule-based" if str(c.get("extraction_method", "")).startswith("rule") else "AI"
    return (
        f'<p class="quote">“{esc(c["quote"])}”</p>'
        f'<p class="cite">Source: {esc(cite(c["evidence_name"], c.get("locator")))} · '
        f"claim {esc(str(c['id'])[:8])} · {method} extraction · "
        f"{esc(STATUS_LABEL.get(c['review_status'], c['review_status']))}</p>"
    )


def _brief_line(b: dict[str, Any]) -> str:
    return (
        f'<p class="quote">“{esc(b["quote"])}”</p>'
        f'<p class="cite">Source: {esc(cite(b["evidence_name"], b.get("locator")))} · '
        f"claim {esc(str(b['id'])[:8])} · "
        f"{esc(STATUS_LABEL.get(b['review_status'], b['review_status']))}</p>"
    )


def executive_summary(snap: dict[str, Any]) -> list[str]:
    ev, claims, cons, events = (
        snap["evidence"],
        snap["claims"],
        snap["contradictions"],
        snap["events"],
    )
    types = Counter(TYPE_LABEL.get(e["type"], e["type"]) for e in ev)
    s: list[str] = []
    s.append(
        f"This report covers the case “{snap['case']['title']}”. It draws on "
        f"{plural(len(ev), 'evidence item')}"
        + (f" ({', '.join(plural(n, t) for t, n in types.most_common())})." if ev else ".")
    )
    done = sum(1 for e in ev if e["status"] == "completed")
    if ev and done < len(ev):
        s.append(
            f"{done} of them were fully processed; the remaining "
            f"{len(ev) - done} could not be used, so the findings below are incomplete."
        )
    if snap["run"] is None:
        s.append(
            "The case has not been analysed yet, so no claims, events or potential "
            "inconsistencies exist. No findings can be reported."
        )
        return s
    verified = sum(1 for c in claims if c["review_status"] == "verified")
    s.append(
        f"The analysis extracted {plural(len(claims), 'source-anchored claim')} "
        f"(statements with a time, date, quantity, identifier or location), each linked "
        f"to its exact position in the source. Reviewers have verified {verified} of them."
    )
    confirmed_events = [e for e in events if e["status"] == "confirmed"]
    if events:
        s.append(
            f"It proposed {plural(len(events), 'possible event')} that several sources may "
            f"describe; reviewers confirmed {len(confirmed_events)} and rejected "
            f"{sum(1 for e in events if e['status'] == 'rejected')}."
        )
        for e in confirmed_events[:3]:
            accounts = "; ".join(
                f"{m['account_label']} says “{m['claim']['quote']}”" for m in e["members"][:4]
            )
            s.append(f"Confirmed event “{e['title']}”: {accounts}.")
    active = [c for c in cons if c["review_status"] != "rejected"]
    if active:
        conf = sum(1 for c in active if c["review_status"] == "confirmed")
        s.append(
            f"{plural(len(active), 'potential inconsistency', 'potential inconsistencies')} "
            f"between sources {'was' if len(active) == 1 else 'were'} identified; "
            f"{conf} {'was' if conf == 1 else 'were'} confirmed by a reviewer as a real "
            "difference between the accounts. A confirmed difference says that the sources "
            "disagree, not which source is right."
        )
    else:
        s.append(
            "No potential inconsistencies were identified under the current rules. "
            "This does not mean the sources agree: only times, quantities and the "
            "order of events are compared."
        )
    return s


def gaps(snap: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for e in snap["evidence"]:
        if e["status"] != "completed":
            out.append(
                f"“{e['name']}” was not processed ({e['status']}); its contents are "
                "not reflected in this report."
            )
    for e in snap["events"]:
        if e["status"] == "rejected":
            continue
        for m in e["missing_links"][:4]:
            out.append(f"Event “{e['title']}”: {m}.")
        if e["status"] == "proposed":
            out.append(
                f"Event “{e['title']}” has not been reviewed; its accounts have not been compared."
            )
    open_c = [
        c for c in snap["contradictions"] if c["review_status"] in ("unreviewed", "unresolved")
    ]
    if open_c:
        out.append(
            f"{plural(len(open_c), 'potential inconsistency', 'potential inconsistencies')}"
            " still await a reviewer decision."
        )
    waiting = sum(
        1 for c in snap["claims"] if c["review_status"] in ("unreviewed", "needs_verification")
    )
    if waiting:
        out.append(
            f"{plural(waiting, 'claim')} have not been checked against their source by a reviewer."
        )
    undated = next((g for g in snap["timeline"]["groups"] if g["date"] is None), None)
    if undated and undated["items"]:
        out.append(
            f"{plural(len(undated['items']), 'timed statement')} carry no stated date, "
            "so they cannot be placed on a specific day."
        )
    return out


def conclusion(snap: dict[str, Any]) -> dict[str, list[str]]:
    supported, uncertain, unknown = [], [], []
    for e in snap["events"]:
        if e["status"] == "confirmed":
            supported.append(
                f"A reviewer agreed that {len(e['members'])} accounts describe "
                f"one occurrence: “{e['title']}”."
            )
    for c in snap["contradictions"]:
        sides = f"“{c['claim_a']['quote']}” and “{c['claim_b']['quote']}”"
        if c["review_status"] == "confirmed":
            supported.append(
                f"The sources disagree ({sides}); a reviewer confirmed the "
                "difference. Which account is accurate is not established."
            )
        elif c["review_status"] in ("unreviewed", "unresolved"):
            uncertain.append(f"Possible difference between {sides} (not yet decided).")
        elif c["review_status"] == "resolved":
            supported.append(
                f"A reviewer resolved the difference between {sides}: "
                f"“{c.get('resolution_note') or ''}”."
            )
    for e in snap["events"]:
        if e["status"] == "proposed":
            uncertain.append(
                f"Whether the accounts grouped as “{e['title']}” concern the same occurrence."
            )
    unknown.append(
        "Which source is accurate where accounts differ, unless a reviewer "
        "recorded a resolution with supporting evidence."
    )
    unknown.append(
        "Anything about intent, honesty, guilt or authenticity: the evidence "
        "and this analysis do not address these questions."
    )
    if not supported:
        supported.append(
            "No finding has been confirmed by a reviewer yet. The analysis "
            "results below are proposals only."
        )
    return {"supported": supported, "uncertain": uncertain, "unknown": unknown}


def render_html(snap: dict[str, Any], *, version: int, ai_summary: list[dict] | None) -> str:
    case = snap["case"]
    run = snap["run"]
    parts: list[str] = []
    add = parts.append
    # Cover
    add('<p class="cover-kicker">EVIDENCEX · INVESTIGATION REPORT</p>')
    add(f"<h1>{esc(case['title'])}</h1>")
    add(
        f'<p class="muted">Case {esc(case["id"])} · report version {version} · generated '
        f"{esc(snap['generated_at'])}</p>"
    )
    if run:
        add(
            f'<p class="muted">Analysis run {esc(run["id"][:8])} · method {esc(run["method"])} · '
            f"{esc(run['status'])}"
            + (f" · completed {esc(run['completed_at'][:16])}" if run.get("completed_at") else "")
            + "</p>"
        )
    add(f'<div class="warn"><p>{esc(DISCLAIMER)}</p></div>')
    add(
        "<h3>Contents</h3><p>1 Executive summary · 2 Case and objective · 3 Scope and evidence "
        "· 4 Methods and limitations · 5 Key claims and their sources · 6 Reconstructed "
        "events and timeline · 7 Possible inconsistencies · 8 Cross-source connections · "
        "9 Evidence gaps and open questions · 10 Confidence and severity · 11 Human review "
        "· 12 Conclusion · 13 Source references</p>"
    )
    # Numbered evidence references, used by "Source references" (section 13).
    ref_no = {e["id"]: i for i, e in enumerate(snap["evidence"], 1)}

    def section(title: str) -> None:
        add(f"<h2>{esc(title)}</h2>")

    section("1 Executive summary")
    for sentence in executive_summary(snap):
        add(f"<p>{esc(guard_or_quote(sentence))}</p>")
    if ai_summary:
        add(
            '<div class="box"><p><b>AI-drafted summary — review before use.</b> Every '
            "sentence below cites claims from this report; uncited sentences were removed."
            "</p>"
        )
        for st in ai_summary:
            add(
                f"<p>{esc(st['text'])} <span class='cite'>[{esc(', '.join(st['citations']))}]"
                "</span></p>"
            )
        add("</div>")

    section("2 Case and objective")
    add(f"<p>{esc(case['description'] or 'No case description was recorded.')}</p>")

    section("3 Scope and evidence examined")
    add(
        "<table><tr><th>#</th><th>File</th><th>Type</th><th>Size</th><th>Processing</th>"
        "<th>SHA-256 (first 16)</th></tr>"
    )
    for i, e in enumerate(snap["evidence"], 1):
        add(
            f"<tr><td>{i}</td><td>{esc(e['name'])}</td>"
            f"<td>{esc(TYPE_LABEL.get(e['type'], e['type']))}"
            f"</td><td>{e['bytes']:,} B</td><td>{esc(e['status'])}</td>"
            f"<td>{esc(e['sha256'][:16])}</td></tr>"
        )
    add("</table>")
    add(
        '<p class="muted">The hash identifies the exact file content examined. It says '
        "nothing about who created the file or whether its content is accurate.</p>"
    )

    section("4 Methods and limitations")
    for line in [
        "Text was taken from PDFs (embedded text, or OCR for scanned pages), images (OCR), "
        "audio and video soundtracks (automatic speech recognition), spreadsheets, CSV "
        "files and emails. Every extracted segment keeps its exact location in the source.",
        "Claims are statements with a checkable feature. Each claim quotes its source "
        "verbatim. Rule-based extraction does not interpret free text beyond its patterns; "
        "AI extraction, when enabled for the case, is labelled per claim.",
        "Events are proposed when claims describe the same kind of occurrence and share an "
        "identifier, a vehicle plate, a named place or, more weakly, the same object word. "
        "Accounts are only compared after a reviewer confirms the grouping.",
        "Machine transcription and OCR can misread words and numbers. Video is examined "
        "through sampled frames and its soundtrack; sampled frames do not cover every moment.",
        "Not compared: free-text names of people and organisations, locations as conflicts "
        "outside confirmed events, and narrative meaning.",
    ]:
        add(f"<p>{esc(line)}</p>")

    section("5 Key claims and their sources")
    picked = key_claims(snap)
    if not picked:
        add("<p>No claims were extracted, so there are no statements to cite.</p>")
    else:
        total = sum(1 for c in snap["claims"] if c["review_status"] != "rejected")
        add(
            "<p>"
            + esc(
                f"The {plural(len(picked), 'claim')} below are those a reviewer verified, or "
                "that take part in an event or a possible inconsistency, followed by others "
                f"in source order ({len(picked)} of {total} claims shown). Each quotes its "
                "source verbatim; a claim is a statement found in the evidence, not a "
                "finding that it is true."
            )
            + "</p>"
        )
        for c in picked:
            n = ref_no.get(str(c["evidence_id"]))
            add(
                f"<p class='tag'>{esc(c['claim_type'])}"
                + (f" · reference [{n}]" if n else "")
                + "</p>"
                + _claim_line(c)
            )

    section("6 Reconstructed events and timeline")
    if not snap["events"]:
        add(
            "<p>No events were proposed. Events need at least two accounts of the same kind "
            "of occurrence that share an anchor.</p>"
        )
    for e in snap["events"]:
        add(f"<h3>{esc(e['title'])}</h3>")
        add(
            f'<p class="tag">Status: {esc(STATUS_LABEL.get(e["status"], e["status"]))} · linked '
            f"by {esc(e['link_basis'])} · association score {e['association_confidence']:.2f} "
            "(heuristic, not a probability)</p>"
        )
        for m in e["members"]:
            add(f"<p><b>{esc(m['account_label'])}</b> — {esc('; '.join(m['match_reasons']))}</p>")
            add(_brief_line(m["claim"]))
        cands = [c for c in e["comparisons"]]
        if cands:
            add("<p><b>How the accounts compare:</b></p>")
            for c in cands:
                add(
                    f"<p>• {esc(c['account_a'])} vs {esc(c['account_b'])}: "
                    f"{esc(c['explanation'])} <span class='tag'>({esc(c['classification'])})"
                    "</span></p>"
                )
        for m in e["missing_links"]:
            add(f"<p class='muted'>Missing link: {esc(m)}</p>")
    groups = snap["timeline"]["groups"]
    if groups:
        add("<h3>Chronological timeline of timed statements</h3>")
        add(
            "<table><tr><th>Date</th><th>Time as written</th><th>Statement</th><th>Source</th></tr>"
        )
        rows = 0
        for g in groups:
            for it in g["items"]:
                if rows >= 80:
                    break
                rows += 1
                c = it["claim"]
                date = g["date"] or "date not stated"
                if it["date_precision"] == "inherited_day":
                    date += " (inherited)"
                add(
                    f"<tr><td>{esc(date)}</td><td>{esc(it['time_raw'] or '—')}</td>"
                    f"<td>{esc(c['quote'][:220])}</td>"
                    f"<td>{esc(cite(c['evidence_name'], c.get('locator')))}</td></tr>"
                )
        add("</table>")
        if snap["timeline"]["total"] > 80:
            add(f"<p class='muted'>Showing 80 of {snap['timeline']['total']} timed statements.</p>")

    section("7 Possible inconsistencies")
    active = [c for c in snap["contradictions"] if c["review_status"] != "rejected"]
    events_by_id = {str(e["id"]): e for e in snap["events"]}
    if not active:
        add(
            "<p>None were identified under the current rules. This is not evidence that the "
            "sources agree.</p>"
        )
    for i, c in enumerate(active, 1):
        ex = c["explanation"]
        add(
            f"<h3>7.{i} Potential {esc(c['category'])} inconsistency"
            + (f" — {esc(c['via_event_title'])}" if c.get("via_event_title") else "")
            + "</h3>"
        )
        add(
            '<p class="tag">Review: '
            f"{esc(STATUS_LABEL.get(c['review_status'], c['review_status']))}"
            f" · severity {esc(c['severity'])} (size of the difference) · detection confidence "
            f"{c['detection_confidence']:.2f} (heuristic)"
            + (
                " · the event grouping was later rejected"
                if c.get("via_event_status") == "rejected"
                else ""
            )
            + "</p>"
        )
        add("<p><b>Conflicting accounts</b></p>")
        add("<p><b>First account</b></p>" + _brief_line(c["claim_a"]))
        add("<p><b>Second account</b></p>" + _brief_line(c["claim_b"]))
        ev = events_by_id.get(str(c.get("via_event_id"))) if c.get("via_event_id") else None
        pair = {str(c["claim_a"]["id"]), str(c["claim_b"]["id"])}
        context = [m for m in (ev or {}).get("members", []) if str(m["claim"]["id"]) not in pair]
        if context:
            add(
                "<p><b>Other accounts of the same event</b> (context for weighing the two "
                "accounts above; being grouped does not make them agree or disagree):</p>"
            )
            for m in context[:6]:
                add(f"<p>• {esc(m['account_label'])}</p>" + _brief_line(m["claim"]))
        add(f"<p><b>Why they may be inconsistent.</b> {esc(ex['why'])}</p>")
        add(f"<p><b>What is uncertain.</b> {esc(ex['uncertain'])}</p>")
        add(f"<p><b>What would resolve it.</b> {esc(ex['would_resolve'])}</p>")
        if ex.get("factors"):
            add(
                "<p class='muted'>Confidence factors: "
                + esc("; ".join(f"{f['factor']} ({f['effect']:+})" for f in ex["factors"]))
                + "</p>"
            )
        if c["alternatives"]:
            add("<p><b>Alternative explanations</b> (possible benign causes to check):</p>")
            for a in c["alternatives"]:
                label = "reviewer" if a["basis"] == "human" else "machine hypothesis"
                add(f"<p>• {esc(a['explanation'])} <span class='tag'>({label})</span></p>")
        if c.get("resolution_note"):
            add(f"<p><b>Reviewer resolution:</b> {esc(c['resolution_note'])}</p>")

    section("8 Cross-source connections")
    shared = [e for e in snap["entities"] if e["evidence_count"] > 1]
    if not shared:
        add(
            "<p>No identifier, vehicle, location or contact appears in more than one evidence "
            "item.</p>"
        )
    else:
        add(
            "<table><tr><th>Entity</th><th>Type</th><th>Evidence items</th><th>Mentions</th>"
            "<th>Written as</th></tr>"
        )
        for e in shared[:40]:
            add(
                f"<tr><td>{esc(e['display_name'])}</td><td>{esc(e['entity_type'])}</td>"
                f"<td>{e['evidence_count']}</td><td>{e['mention_count']}</td>"
                f"<td>{esc(', '.join(e['aliases'][:5]))}</td></tr>"
            )
        add("</table>")
        add(
            "<p class='muted'>Only identical normalised values share an entity; similar values "
            "are never merged without a reviewer.</p>"
        )

    section("9 Evidence gaps and open questions")
    gl = gaps(snap)
    for g in gl or [
        "No gaps were detected by the automated checks; this does not mean the "
        "evidence is complete."
    ]:
        add(f"<p>• {esc(g)}</p>")

    section("10 How confidence and severity are expressed")
    for line in [
        "Extraction confidence: an AI model's self-assessment of how faithfully a claim "
        "reflects its quote (absent for rule-based claims).",
        "Engine confidence: the OCR or speech engine's own score for the source text.",
        "Event association score: a heuristic for how strongly the rules link the grouped "
        "claims (identifier 0.80, plate 0.70, place 0.55, object word 0.35, adjusted for "
        "dates and number of sources).",
        "Detection confidence: a heuristic for how cleanly a comparison rule matched, "
        "lowered for transcription, OCR, hedging, approximate times and indirect links.",
        "Severity: the size of a difference (for times: low ≤30 min, medium ≤120 min, high "
        "above), not its importance and not its truth.",
        "None of these values is a statistically calibrated probability: there is no "
        "labelled evaluation data to calibrate them against.",
    ]:
        add(f"<p>• {esc(line)}</p>")

    section("11 Human review")
    by_action = Counter(r["action"] for r in snap["reviews"])
    add(
        "<p>"
        + esc(
            f"{plural(len(snap['reviews']), 'review action')} are recorded"
            + (
                ": " + ", ".join(f"{a} {n}" for a, n in by_action.most_common())
                if by_action
                else ""
            )
            + "."
        )
        + "</p>"
    )
    ch = snap["audit_chain"]
    add(
        "<p>"
        + esc(
            "Audit trail integrity: "
            + ("intact" if ch["intact"] else f"BROKEN ({ch['reason']})")
            + f" — {ch['checked']} chained action(s), {ch['legacy_unchained']} recorded before "
            "chaining was introduced."
        )
        + "</p>"
    )
    if snap["reviews"]:
        add("<table><tr><th>When</th><th>Who</th><th>Target</th><th>Action</th><th>Note</th></tr>")
        for r in snap["reviews"][:25]:
            add(
                f"<tr><td>{esc(r['created_at'][:16])}</td><td>{esc(r['reviewer'])}</td>"
                f"<td>{esc(r['target_type'])}</td><td>{esc(r['action'])}</td>"
                f"<td>{esc((r['note'] or '')[:120])}</td></tr>"
            )
        add("</table>")
    add("<p class='muted'>Reviewer identity is the signed-in account that recorded the action.</p>")

    section("12 Conclusion")
    concl = conclusion(snap)
    for heading, key in [
        ("What the evidence supports", "supported"),
        ("What remains uncertain", "uncertain"),
        ("What cannot be determined from this evidence", "unknown"),
    ]:
        add(f"<h3>{heading}</h3>")
        for line in concl[key] or ["Nothing recorded."]:
            add(f"<p>• {esc(line)}</p>")

    section("13 Source references")
    add(
        "<p>Every quotation in this report cites one of the evidence items below and the "
        "exact location inside it (page and box, image region, time range, frame, sheet and "
        "cell, or e-mail part). The full SHA-256 identifies the exact file examined.</p>"
    )
    per_ev = Counter(
        str(c["evidence_id"]) for c in snap["claims"] if c["review_status"] != "rejected"
    )
    if not snap["evidence"]:
        add("<p>No evidence items were examined.</p>")
    for e in snap["evidence"]:
        add(
            f"<p><b>[{ref_no[e['id']]}] {esc(e['name'])}</b> — "
            f"{esc(TYPE_LABEL.get(e['type'], e['type']))}, {e['bytes']:,} bytes, "
            f"{esc(plural(per_ev.get(e['id'], 0), 'claim'))} extracted, processing "
            f"{esc(e['status'])}</p>"
            f"<p class='cite'>SHA-256 {esc(e['sha256'])}</p>"
        )
    add("<h3>Limitations and disclaimer</h3>")
    add(
        "<p>This report is generated from the evidence and the review decisions recorded "
        "in EvidenceX at the time shown on the cover. Later uploads, reprocessing or review "
        "decisions are not reflected; generate a new version to include them.</p>"
    )
    add(f'<div class="warn"><p>{esc(DISCLAIMER)}</p></div>')
    return "<html><body>" + "".join(parts) + "</body></html>"


def key_claims(snap: dict[str, Any], limit: int = 25) -> list[dict[str, Any]]:
    """Claims worth citing up front: verified first, then those used by events or possible
    inconsistencies, then the rest in source order. Rejected claims are left out."""
    used: set[str] = set()
    for e in snap["events"]:
        used.update(str(m["claim"]["id"]) for m in e.get("members", []))
    for c in snap["contradictions"]:
        used.update({str(c["claim_a"]["id"]), str(c["claim_b"]["id"])})
    pool = [c for c in snap["claims"] if c["review_status"] != "rejected"]

    def rank(c: dict[str, Any]) -> int:
        if c["review_status"] == "verified":
            return 0
        return 1 if str(c["id"]) in used else 2

    return sorted(pool, key=rank)[:limit]  # sorted() is stable: source order within a rank


def guard_or_quote(sentence: str) -> str:
    """Guard generated text; parts inside “…” are evidence quotes and exempt."""
    import re

    guard(re.sub(r"“[^”]*”", "“…”", sentence))
    return sentence


# --- PDF ----------------------------------------------------------------------------


def html_to_pdf(html_text: str, *, title: str, header: str) -> tuple[bytes, int]:
    import pymupdf

    story = pymupdf.Story(html=html_text, user_css=REPORT_CSS)
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    mediabox = pymupdf.paper_rect("a4")
    where = mediabox + (54, 62, -54, -58)
    headings: list[tuple[int, str, int]] = []
    page = 0

    def record(pos: Any) -> None:
        if getattr(pos, "heading", 0) and (getattr(pos, "open_close", 0) & 1) and pos.text:
            headings.append((int(pos.heading), str(pos.text).strip(), page))

    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _filled = story.place(where)
        story.element_positions(record)
        story.draw(device)
        writer.end_page()
        page += 1
        if page > 400:
            break
    writer.close()
    doc = pymupdf.open("pdf", buf.getvalue())
    total = doc.page_count
    for i, p in enumerate(doc):
        p.insert_text((54, 36), header[:110], fontsize=7.5, color=(0.36, 0.40, 0.47))
        p.insert_text(
            (54, p.rect.height - 28),
            "EvidenceX analytical aid — not a determination of fact, guilt or authenticity",
            fontsize=7,
            color=(0.45, 0.48, 0.55),
        )
        p.insert_text(
            (p.rect.width - 110, p.rect.height - 28),
            f"Page {i + 1} of {total}",
            fontsize=7.5,
            color=(0.36, 0.40, 0.47),
        )
    toc = [
        [min(level, 3) if level > 1 else 1, text[:80], pg + 1]
        for level, text, pg in headings
        if level in (1, 2, 3)
    ]
    if toc:
        toc[0][0] = 1
        fixed, prev = [], 1
        for level, text, pg in toc:
            level = min(level, prev + 1)
            fixed.append([level, text, pg])
            prev = level
        try:
            doc.set_toc(fixed)
        except Exception:  # noqa: BLE001 - bookmarks are a convenience only
            pass
    from app.modules.analysis.pdf_notice import pdf_metadata

    doc.set_metadata(pdf_metadata(title, "Investigation report (analytical aid)"))
    data = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return data, total


def defaultdict_list() -> defaultdict:
    return defaultdict(list)
