"""Cross-Modal Contradiction Engine (rule-based) and alternative explanations.

Pure functions. A potential contradiction is proposed only when two claims from
DIFFERENT evidence items mention the SAME entity record (identical normalized
identifier) and make comparable statements about the same attribute (the same
``predicate_key``). Claims that merely look similar, or that concern different
entities, are never paired. The output is a potential inconsistency for human review,
never a finding that either source is false.

Detection confidence is a heuristic score of how cleanly the rule matched, reduced
for transcription/OCR sources and hedged wording. It is not a probability that a
contradiction exists, and says nothing about which source is right.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ENGINE = "rule_based_v1"
TIME_TOLERANCE_MINUTES = 10


@dataclass
class ClaimFacts:
    id: str
    evidence_id: str
    evidence_name: str
    modality: str
    quote: str
    predicate_key: str | None
    event_time: dict[str, Any] | None
    object_value: str | None
    claim_type: str
    uncertainty: list[str]
    entity_ids: set[str] = field(default_factory=set)


@dataclass
class AlternativeDraft:
    explanation: str
    supporting_evidence: str | None
    weakening_evidence: str | None
    missing_information: str | None
    verification_recommendation: str | None
    basis: str = "machine_hypothesis"


@dataclass
class ContradictionDraft:
    claim_a_id: str
    claim_b_id: str
    via_entity_id: str
    category: str
    explanation: dict[str, str]
    severity: str
    detection_confidence: float
    uncertainty: list[str]
    alternatives: list[AlternativeDraft]
    origin: str = ENGINE


def _fmt_minutes(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _fmt_interval(interval: tuple[int, int]) -> str:
    """'10:30' for an exact time, '12:00-23:59' for a range."""
    start, end = interval
    return _fmt_minutes(start) if start == end else f"{_fmt_minutes(start)}-{_fmt_minutes(end)}"


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def _interval(t: dict[str, Any] | None) -> tuple[int, int] | None:
    if not t:
        return None
    if isinstance(t.get("minutes"), int):
        return t["minutes"], t["minutes"]
    rng = t.get("range")
    if isinstance(rng, list) and len(rng) == 2 and all(isinstance(x, int) for x in rng):
        return rng[0], rng[1]
    return None


def _gap(a: tuple[int, int], b: tuple[int, int]) -> int:
    """Minutes between two intervals; 0 when they overlap."""
    if a[1] < b[0]:
        return b[0] - a[1]
    if b[1] < a[0]:
        return a[0] - b[1]
    return 0


def _confidence(a: ClaimFacts, b: ClaimFacts, imprecise: bool) -> tuple[float, list[str]]:
    score, notes = 0.7, []
    for c in (a, b):
        if c.modality == "audio":
            score -= 0.15
            notes.append(f"'{c.evidence_name}' is a machine transcription; words may be misheard")
        if c.modality == "image":
            score -= 0.1
            notes.append(f"'{c.evidence_name}' text comes from OCR; characters may be misread")
        if c.modality == "video":
            score -= 0.15
            notes.append(
                f"'{c.evidence_name}' text comes from a video soundtrack transcript or frame "
                "OCR; words may be misheard or misread"
            )
        if any(u.startswith("hedged wording") for u in c.uncertainty):
            score -= 0.15
            notes.append(f"'{c.evidence_name}' uses hedged wording")
        if any("misheard" in u for u in c.uncertainty):
            score -= 0.1
    if imprecise:
        score -= 0.1
        notes.append("at least one time is approximate, not exact")
    if a.predicate_key != b.predicate_key:
        score -= 0.1
    return round(max(0.1, min(0.9, score)), 2), notes


def _alternatives(a: ClaimFacts, b: ClaimFacts, category: str) -> list[AlternativeDraft]:
    alts = [
        AlternativeDraft(
            "The two sources may describe different events (for example a planned time and "
            "an actual time, or two separate deliveries).",
            None,
            "A record showing a single event for this identifier on that day.",
            "Whether both statements refer to the same occasion and date.",
            "Check whether the sources refer to the same date and occurrence.",
        )
    ]
    if category == "temporal":
        alts.append(
            AlternativeDraft(
                "The times may have been recorded in different time zones or clocks.",
                None,
                "Both sources state the same time zone, or come from the same system clock.",
                "The time zone or clock used by each source.",
                "Confirm the time zone and clock source of each record.",
            )
        )
    for c in (a, b):
        if c.modality == "audio" or any(u.startswith("hedged wording") for u in c.uncertainty):
            alts.append(
                AlternativeDraft(
                    f"'{c.evidence_name}' may be an approximate recollection rather than a "
                    "recorded value.",
                    f'The source says: "{c.quote}"'
                    if any(u.startswith("hedged wording") for u in c.uncertainty)
                    else None,
                    "A precise record from the same person or system.",
                    "How the speaker or author knew the value.",
                    "Ask whether the statement was an estimate.",
                )
            )
        if c.modality == "audio":
            alts.append(
                AlternativeDraft(
                    f"The speech engine may have misheard a word or number in '{c.evidence_name}'.",
                    None,
                    "Listening to the segment confirms the transcript wording.",
                    "Human verification of the transcript.",
                    "Play the audio segment and compare it with the transcript.",
                )
            )
        if c.modality == "image":
            alts.append(
                AlternativeDraft(
                    f"OCR may have misread characters in '{c.evidence_name}'.",
                    None,
                    "The image clearly shows the transcribed characters.",
                    "A human reading of the image region.",
                    "Open the image at the source region and compare.",
                )
            )
        if c.modality == "tabular":
            alts.append(
                AlternativeDraft(
                    f"'{c.evidence_name}' may contain a data-entry error or an outdated value.",
                    None,
                    "Audit history showing the value was entered and not changed.",
                    "Who entered the value and when.",
                    "Check the system of record or its change history.",
                )
            )
    return alts


def _stated_date(quote: str) -> str | None:
    """The first unambiguous date written in the statement itself, if any."""
    from app.modules.analysis.temporal import dates_in

    return next((r.value for r in dates_in(quote) if r.value), None)


def _temporal(a: ClaimFacts, b: ClaimFacts, entity_id: str) -> ContradictionDraft | None:
    ia, ib = _interval(a.event_time), _interval(b.event_time)
    if ia is None or ib is None:
        return None  # unparsed or ambiguous ("1030") values are never compared
    da, db = _stated_date(a.quote), _stated_date(b.quote)
    if da and db and da != db:
        return None  # times of day on two different stated dates are not comparable
    gap = _gap(ia, ib)
    if gap <= TIME_TOLERANCE_MINUTES:
        return None
    imprecise = ia[0] != ia[1] or ib[0] != ib[1]
    confidence, notes = _confidence(a, b, imprecise)
    severity = "high" if gap > 120 else "medium" if gap > 30 else "low"
    raw_a, raw_b = a.event_time["raw"], b.event_time["raw"]
    what = (a.predicate_key or "time").replace("_", " ")
    return ContradictionDraft(
        claim_a_id=a.id,
        claim_b_id=b.id,
        via_entity_id=entity_id,
        category="temporal",
        explanation={
            "first_states": f"'{a.evidence_name}' states: \"{a.quote}\"",
            "second_states": f"'{b.evidence_name}' states: \"{b.quote}\"",
            "why": (
                f"Both mention the same identifier and give {_article(what)} {what} time, but "
                f"'{raw_a}' and '{raw_b}' are at least {gap} minutes apart "
                f"(compared as {_fmt_interval(ia)} and {_fmt_interval(ib)})."
            ),
            "uncertain": (
                "Whether both statements concern the same date and the same "
                "occurrence; neither source states a date for this time."
                if not (a.event_time.get("date_known") and b.event_time.get("date_known"))
                else "Whether both statements concern the same occurrence."
            ),
            "would_resolve": (
                "A timestamped system record (e.g. gate log or GPS trace) for "
                "this entity on the relevant date."
            ),
        },
        severity=severity,
        detection_confidence=confidence,
        uncertainty=notes,
        alternatives=_alternatives(a, b, "temporal"),
    )


def _number(value: str | None) -> float | None:
    if not value:
        return None
    import re

    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", value)
    return float(m.group(0).replace(",", "")) if m else None


def _quantity(a: ClaimFacts, b: ClaimFacts, entity_id: str) -> ContradictionDraft | None:
    if a.claim_type != "quantity" or b.claim_type != "quantity":
        return None
    na, nb = _number(a.object_value), _number(b.object_value)
    unit_a = (a.object_value or "").split()[-1].lower() if a.object_value else ""
    unit_b = (b.object_value or "").split()[-1].lower() if b.object_value else ""
    if na is None or nb is None or na == nb or unit_a.rstrip("s") != unit_b.rstrip("s"):
        return None
    confidence, notes = _confidence(a, b, False)
    return ContradictionDraft(
        claim_a_id=a.id,
        claim_b_id=b.id,
        via_entity_id=entity_id,
        category="quantity",
        explanation={
            "first_states": f"'{a.evidence_name}' states: \"{a.quote}\"",
            "second_states": f"'{b.evidence_name}' states: \"{b.quote}\"",
            "why": (
                f"Both refer to the same entity but report different amounts "
                f"('{a.object_value}' vs '{b.object_value}')."
            ),
            "uncertain": "Whether the amounts describe the same consignment at the same stage.",
            "would_resolve": "The manifest or weighbridge record for this entity.",
        },
        severity="medium",
        detection_confidence=confidence,
        uncertainty=notes,
        alternatives=_alternatives(a, b, "quantity"),
    )


def detect(claims: list[ClaimFacts]) -> list[ContradictionDraft]:
    """Potential contradictions between claims of different evidence items."""
    by_entity: dict[str, list[ClaimFacts]] = {}
    for c in claims:
        for e in c.entity_ids:
            by_entity.setdefault(e, []).append(c)
    out: dict[tuple[str, str, str], ContradictionDraft] = {}
    for entity_id, group in by_entity.items():
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                if a.evidence_id == b.evidence_id:
                    continue
                if not a.predicate_key or a.predicate_key != b.predicate_key:
                    continue  # never compare different attributes
                x, y = (a, b) if a.id < b.id else (b, a)
                for found in (_temporal(x, y, entity_id), _quantity(x, y, entity_id)):
                    if found:
                        out.setdefault((x.id, y.id, found.category), found)
    return list(out.values())


# --- Phase 2: comparisons inside reviewer-confirmed events -------------------------
#
# Identifier-based detection above is unchanged. The functions below compare the
# accounts of an event a REVIEWER has confirmed, so claims without a shared identifier
# ("the truck") can be compared once a person has agreed they describe one occurrence.


def confidence_breakdown(
    a: ClaimFacts, b: ClaimFacts, *, imprecise: bool, link_basis: str
) -> tuple[float, list[str], list[dict[str, Any]]]:
    """Heuristic detection confidence with every factor that moved it.

    Not a probability. It reflects how cleanly the rule matched given source quality
    (OCR/ASR), hedging, imprecision and how the claims were linked.
    """
    score, notes = _confidence(a, b, imprecise)
    factors: list[dict[str, Any]] = [{"factor": "base rule match", "effect": 0.7}]
    for c in (a, b):
        if c.modality == "audio":
            factors.append({"factor": f"machine transcription: {c.evidence_name}", "effect": -0.15})
        if c.modality == "image":
            factors.append({"factor": f"OCR text: {c.evidence_name}", "effect": -0.1})
        if any(u.startswith("hedged wording") for u in c.uncertainty):
            factors.append({"factor": f"hedged wording: {c.evidence_name}", "effect": -0.15})
    if imprecise:
        factors.append({"factor": "approximate time", "effect": -0.1})
    if link_basis != "identifier":
        score = round(max(0.1, score - 0.15), 2)
        factors.append(
            {"factor": "linked by reviewer-confirmed event, not by an identifier", "effect": -0.15}
        )
        notes.append("the two claims are linked by a confirmed event, not by a shared identifier")
    return score, notes, factors


def _facts_from_member(m: Any) -> ClaimFacts:
    c = m.claim
    return ClaimFacts(
        id=c.id,
        evidence_id=c.evidence_id,
        evidence_name=m.account_label,
        modality=c.modality,
        quote=c.quote,
        predicate_key=c.predicate_key,
        event_time=None,
        object_value=None,
        claim_type="date_time",
        uncertainty=list(c.uncertainty),
    )


def detect_in_event(
    *,
    event_title: str,
    link_basis: str,
    missing_links: list[str],
    comparisons: list[Any],
) -> list[ContradictionDraft]:
    """Potential inconsistencies for the candidate comparisons of a confirmed event."""
    out: list[ContradictionDraft] = []
    for cmp in comparisons:
        if not cmp.is_candidate:
            continue
        x, y = (cmp.a, cmp.b) if cmp.a.claim.id < cmp.b.claim.id else (cmp.b, cmp.a)
        fa, fb = _facts_from_member(x), _facts_from_member(y)
        ia, ib = x.claim.interval, y.claim.interval
        imprecise = ia[0] != ia[1] or ib[0] != ib[1]
        confidence, notes, factors = confidence_breakdown(
            fa, fb, imprecise=imprecise, link_basis=link_basis
        )
        gap = cmp.gap_minutes or 0
        severity = "high" if gap > 120 else "medium" if gap > 30 else "low"
        alternatives = [
            AlternativeDraft(
                "The grouped accounts may describe different occurrences (for example two "
                "vehicles, or two visits on the same day).",
                None,
                "A record identifying the specific vehicle or shipment in each account.",
                "Whether every account refers to the same object and occasion.",
                "Check each account for an identifier, plate or reference number.",
            ),
            *_alternatives(fa, fb, "temporal"),
        ]
        if cmp.classification == "possible_timezone":
            severity = "low"
            confidence = round(max(0.1, confidence - 0.15), 2)
            factors.append(
                {"factor": "whole-hour difference, no time zone stated", "effect": -0.15}
            )
            alternatives.insert(
                0,
                AlternativeDraft(
                    "The difference is close to a whole number of hours and no time zone is "
                    "stated; the sources may use different clocks or time zones.",
                    None,
                    "Both sources state the same time zone.",
                    "The time zone of each record.",
                    "Confirm each source's time zone.",
                ),
            )
        if x.attribution and y.attribution and x.claim.evidence_id == y.claim.evidence_id:
            notes.append(
                f"both accounts are quoted in the same document ({x.claim.evidence_name}) "
                f"and attributed to different sources ({x.attribution}; {y.attribution})"
            )
        out.append(
            ContradictionDraft(
                claim_a_id=x.claim.id,
                claim_b_id=y.claim.id,
                via_entity_id="",
                category="temporal",
                explanation={
                    "first_states": f"'{x.account_label}' states: \"{x.claim.quote}\"",
                    "second_states": f"'{y.account_label}' states: \"{y.claim.quote}\"",
                    "why": (
                        f"A reviewer grouped these accounts as one event ({event_title}). "
                        f"{cmp.explanation}"
                    ),
                    "uncertain": (
                        "Whether both accounts describe exactly the same occurrence. "
                        + (" ".join(missing_links[:3]) if missing_links else "")
                    ).strip(),
                    "would_resolve": (
                        "A timestamped system record (gate log, GPS trace, signed receipt) that "
                        "identifies the specific vehicle or shipment."
                    ),
                    "classification": cmp.classification,
                    "factors": factors,
                },
                severity=severity,
                detection_confidence=confidence,
                uncertainty=notes,
                alternatives=alternatives,
            )
        )
    return out


def detect_sequence(
    conflicts: list[tuple[Any, Any, str]], link_basis: str
) -> list[ContradictionDraft]:
    """Potential order inconsistencies between two confirmed events (see events.py)."""
    out: list[ContradictionDraft] = []
    for first, later, why in conflicts:
        fa, fb = _facts_from_member(first), _facts_from_member(later)
        confidence, notes, factors = confidence_breakdown(
            fa, fb, imprecise=False, link_basis=link_basis
        )
        x, y = (first, later) if first.claim.id < later.claim.id else (later, first)
        out.append(
            ContradictionDraft(
                claim_a_id=x.claim.id,
                claim_b_id=y.claim.id,
                via_entity_id="",
                category="sequence",
                explanation={
                    "first_states": f"'{first.account_label}' states: \"{first.claim.quote}\"",
                    "second_states": f"'{later.account_label}' states: \"{later.claim.quote}\"",
                    "why": why,
                    "uncertain": "Whether both events concern the same object on the same trip.",
                    "would_resolve": "A dated movement record for this object.",
                    "classification": "sequence_conflict",
                    "factors": factors,
                },
                severity="medium",
                detection_confidence=confidence,
                uncertainty=notes,
                alternatives=[
                    AlternativeDraft(
                        "The events may belong to different trips or days.",
                        None,
                        "A single trip record covering both events.",
                        "Trip or reference numbers.",
                        "Match both events to one trip record.",
                    ),
                    *_alternatives(fa, fb, "temporal"),
                ],
            )
        )
    return out
