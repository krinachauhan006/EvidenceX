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


def _temporal(a: ClaimFacts, b: ClaimFacts, entity_id: str) -> ContradictionDraft | None:
    ia, ib = _interval(a.event_time), _interval(b.event_time)
    if ia is None or ib is None:
        return None  # unparsed or ambiguous ("1030") values are never compared
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
