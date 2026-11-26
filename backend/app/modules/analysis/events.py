"""Event reconstruction (pure functions): propose which claims MAY describe the same
real-world occurrence, explain why, and classify how their accounts compare.

A proposal is never a finding. It states its anchor, the reasons each claim was
included, what links are missing, and a heuristic ``association_confidence``. A
reviewer confirms, rejects, splits or regroups it. Only confirmed events are used to
create potential inconsistencies (see ``compare_accounts``).

Anchors, strongest first:
  identifier (exact normalized id, e.g. NS88421)  0.80
  vehicle    (exact plate)                         0.70
  location   (exact named place, e.g. Warehouse A) 0.55
  object     (same object word: truck, van, ...)   0.35
Planned and actual events (planned_arrival vs arrival) are different event types and
are never grouped together.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.modules.analysis.temporal import comparable

EVENT_TYPES = {
    "arrival": "Arrival",
    "departure": "Departure",
    "dispatch": "Dispatch",
    "delivery": "Delivery",
    "pickup": "Pickup",
    "loading": "Loading",
    "inspection": "Inspection",
    "assignment": "Assignment",
    "planned_arrival": "Planned arrival",
    "planned_departure": "Planned departure",
    "planned_dispatch": "Planned dispatch",
    "planned_delivery": "Planned delivery",
}
# Typical order of logistics steps for the same anchor on the same day.
SEQUENCE_ORDER = {
    "dispatch": 0,
    "loading": 0,
    "pickup": 0,
    "departure": 1,
    "arrival": 2,
    "delivery": 3,
    "inspection": 4,
}
ANCHOR_WEIGHT = {"identifier": 0.80, "vehicle": 0.70, "location": 0.55, "object": 0.35}
ANCHOR_RANK = {"identifier": 0, "vehicle": 1, "location": 2, "object": 3}
OBJECT_CLASSES = {
    "truck": "truck",
    "lorry": "truck",
    "van": "van",
    "vehicle": "vehicle",
    "trailer": "trailer",
    "shipment": "shipment",
    "consignment": "shipment",
    "parcel": "parcel",
    "package": "parcel",
    "container": "container",
}
_OBJECT = re.compile(r"\b(" + "|".join(OBJECT_CLASSES) + r")s?\b", re.I)
# A source named at the start of a statement: "Delivery receipt: ...", "Gate log -",
# "A separate witness statement says ...", "Witness audio: ...".
_ATTRIBUTION = re.compile(
    r"^\W*(?:\d{4}-\d{2}-\d{2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?\s*[—–-]\s*)?"
    r"(?:(?:a|an|the|one|another|separate|second|first)\s+)*"
    r"(?P<who>[A-Za-z][A-Za-z ]{2,40}?)"
    r"\s*(?::|—|–|\bstates?\b|\bsays?\b|\breports?\b|\brecords?\b|\bshows?\b|\bnotes?\b|"
    r"\bconfirms?\b|\bindicates?\b)",
    re.I,
)
_SOURCE_NOUNS = re.compile(
    r"\b(receipt|statement|log|system|scan|record|report|manifest|email|message|audio|"
    r"camera|cctv|footage|telematics|gps|witness|driver|guard|clerk|dispatcher|register)\b",
    re.I,
)
TOLERANCE_MIN = 10
ROUNDING_MIN = 15


@dataclass
class ClaimInfo:
    id: str
    evidence_id: str
    evidence_name: str
    modality: str
    quote: str
    predicate_key: str | None
    interval: tuple[int, int] | None  # minutes after midnight; (x, x) when exact
    time_raw: str | None
    time_precision: str | None
    date: str | None
    date_precision: str
    date_source: str | None
    tz: str | None
    uncertainty: list[str]
    entities: list[tuple[str, str, str, str]] = field(default_factory=list)
    # (entity_type, normalized_key, display_name, entity_id)


@dataclass
class Member:
    claim: ClaimInfo
    attribution: str | None
    account_label: str
    reasons: list[str]


@dataclass
class EventProposal:
    event_type: str
    title: str
    anchor_kind: str
    anchor_key: str
    anchor_display: str
    anchor_entity_id: str | None
    event_date: str | None
    date_precision: str
    link_basis: str
    association_confidence: float
    factors: list[dict[str, Any]]
    missing_links: list[str]
    members: list[Member]
    signature: str


def attribution_of(quote: str) -> str | None:
    """A source named at the start of the statement, normalized ('delivery receipt')."""
    m = _ATTRIBUTION.match(quote.strip())
    if not m:
        return None
    who = " ".join(m.group("who").lower().split())
    if not _SOURCE_NOUNS.search(who):
        return None  # "Truck arrived:" is not a source
    words = who.split()
    return " ".join(words[-3:])


def object_classes(quote: str) -> list[str]:
    """Every object class named in the statement, in order, without repeats."""
    return list(dict.fromkeys(OBJECT_CLASSES[m.group(1).lower()] for m in _OBJECT.finditer(quote)))


def object_class(quote: str) -> str | None:
    found = object_classes(quote)
    return found[0] if found else None


def _anchors(c: ClaimInfo) -> list[tuple[str, str, str, str | None]]:
    out: list[tuple[str, str, str, str | None]] = []
    for etype, key, display, eid in c.entities:
        if etype in ("shipment", "identifier"):
            out.append(("identifier", key, display, eid))
        elif etype == "vehicle":
            out.append(("vehicle", key, display, eid))
        elif etype == "location":
            out.append(("location", key, display, eid))
    for obj in object_classes(c.quote):
        out.append(("object", obj, obj, None))
    return out


def explicitly_different(claims: list[ClaimInfo]) -> bool:
    """True when the claims name two or more different vehicles, or two or more
    different shipment/record identifiers."""
    groups = {"vehicle": "vehicle", "shipment": "id", "identifier": "id"}
    seen: dict[str, set[str]] = defaultdict(set)
    for c in claims:
        for etype, key, _display, _eid in c.entities:
            if etype in groups:
                seen[groups[etype]].add(key)
    return any(len(keys) > 1 for keys in seen.values())


def account_label(c: ClaimInfo, attribution: str | None) -> str:
    return f"{c.evidence_name} — {attribution}" if attribution else c.evidence_name


def _date_buckets(claims: list[ClaimInfo]) -> list[tuple[str | None, list[ClaimInfo]]]:
    """Split by date. Undated claims join the single dated bucket if there is exactly
    one; otherwise they form their own 'date not stated' bucket."""
    dated: dict[str, list[ClaimInfo]] = defaultdict(list)
    undated: list[ClaimInfo] = []
    for c in claims:
        (dated[c.date] if c.date else undated).append(c)
    if len(dated) == 1:
        (only,) = dated
        return [(only, dated[only] + undated)]
    out: list[tuple[str | None, list[ClaimInfo]]] = sorted(dated.items())
    if undated:
        out.append((None, undated))
    return out


def _confidence(kind: str, members: list[Member], date: str | None) -> tuple[float, list]:
    factors = [
        {
            "factor": f"anchor: {kind}",
            "effect": ANCHOR_WEIGHT[kind],
            "detail": {
                "identifier": "the claims share an exact identifier",
                "vehicle": "the claims share an exact vehicle plate",
                "location": "the claims share an exact named location",
                "object": "the claims only share an object word (no identifier)",
            }[kind],
        }
    ]
    score = ANCHOR_WEIGHT[kind]
    sources = {m.claim.evidence_id for m in members}
    if len(sources) > 1:
        bonus = min(0.1, 0.05 * (len(sources) - 1))
        score += bonus
        factors.append(
            {
                "factor": "independent evidence items",
                "effect": round(bonus, 2),
                "detail": f"{len(sources)} different evidence items describe it",
            }
        )
    weak_dates = [m for m in members if m.claim.date_precision != "day"]
    if weak_dates:
        score -= 0.1
        factors.append(
            {
                "factor": "date not stated in every account",
                "effect": -0.1,
                "detail": f"{len(weak_dates)} account(s) have an inherited or unknown date",
            }
        )
    elif date:
        score += 0.05
        factors.append({"factor": "same stated date", "effect": 0.05, "detail": date})
    return round(max(0.1, min(0.9, score)), 2), factors


def propose_events(claims: list[ClaimInfo]) -> list[EventProposal]:
    """Proposals from rule-based association. Deterministic for the same input."""
    groups: dict[tuple[str, str, str], list[ClaimInfo]] = defaultdict(list)
    display: dict[tuple[str, str, str], tuple[str, str | None]] = {}
    for c in claims:
        if c.predicate_key not in EVENT_TYPES:
            continue
        for kind, key, disp, eid in _anchors(c):
            gk = (c.predicate_key, kind, key)
            groups[gk].append(c)
            display.setdefault(gk, (disp, eid))
    proposals: list[EventProposal] = []
    for (etype, kind, key), members_c in groups.items():
        for date, bucket in _date_buckets(members_c):
            members: list[Member] = []
            for c in bucket:
                attr = attribution_of(c.quote)
                reasons = [f"describes the same kind of event: {EVENT_TYPES[etype].lower()}"]
                reasons.append(
                    {
                        "identifier": f"mentions the identifier {display[(etype, kind, key)][0]}",
                        "vehicle": f"mentions the vehicle {display[(etype, kind, key)][0]}",
                        "location": f"mentions the location {display[(etype, kind, key)][0]}",
                        "object": f"mentions the same object: {key}",
                    }[kind]
                )
                if c.date and date:
                    reasons.append(
                        f"date {c.date} ({'stated' if c.date_precision == 'day' else 'inherited'})"
                    )
                elif date:
                    reasons.append("no date stated; grouped with the only dated account")
                members.append(Member(c, attr, account_label(c, attr), reasons))
            accounts = {(m.claim.evidence_id, m.attribution) for m in members}
            if len(accounts) < 2:
                continue
            if kind in ("object", "location") and explicitly_different(bucket):
                # "the truck" in two accounts that name two different plates (or ids)
                # is not one occurrence. Ambiguous grouping is never proposed; a
                # reviewer can still group claims by hand.
                continue
            missing: list[str] = []
            if kind == "object":
                missing.append(
                    f"no shared identifier, plate or named place; linked only by the word "
                    f"'{key}'. The accounts may concern different {key}s."
                )
            if kind == "location":
                missing.append("no shared identifier; linked by the named location only")
            for m in members:
                if m.claim.date_precision != "day":
                    missing.append(
                        f"'{m.account_label}' does not state a date"
                        + (
                            " (date inherited from the document)"
                            if m.claim.date_precision == "inherited_day"
                            else ""
                        )
                    )
                if m.claim.interval is None:
                    missing.append(f"'{m.account_label}' gives no comparable time")
            if not any(m.claim.tz for m in members):
                missing.append("no account states a time zone")
            conf, factors = _confidence(kind, members, date)
            disp, eid = display[(etype, kind, key)]
            title = f"{EVENT_TYPES[etype]} — {disp}" + (f" on {date}" if date else "")
            ids = sorted(m.claim.id for m in members)
            sig = hashlib.sha256(
                "|".join([etype, kind, key, date or "-", *ids]).encode()
            ).hexdigest()
            precision = (
                "day"
                if date and all(m.claim.date_precision == "day" for m in members)
                else ("inherited_day" if date else "unknown")
            )
            proposals.append(
                EventProposal(
                    etype,
                    title,
                    kind,
                    key,
                    disp,
                    eid,
                    date,
                    precision,
                    "identifier" if kind in ("identifier", "vehicle") else "context",
                    conf,
                    factors,
                    missing,
                    members,
                    sig,
                )
            )
    # The same set of claims grouped by a weaker anchor adds nothing: keep the strongest.
    proposals.sort(key=lambda p: (ANCHOR_RANK[p.anchor_kind], -len(p.members)))
    kept: list[EventProposal] = []
    seen_sets: list[set[str]] = []
    for p in proposals:
        ids = {m.claim.id for m in p.members}
        if any(ids <= s for s in seen_sets):
            continue
        seen_sets.append(ids)
        kept.append(p)
    return kept


# --- comparing the accounts of one event -----------------------------------------


@dataclass
class Comparison:
    a: Member
    b: Member
    classification: str
    gap_minutes: int | None
    explanation: str

    @property
    def is_candidate(self) -> bool:
        return self.classification in ("conflict_candidate", "possible_timezone")


def _gap(x: tuple[int, int], y: tuple[int, int]) -> int:
    if x[1] < y[0]:
        return y[0] - x[1]
    if y[1] < x[0]:
        return x[0] - y[1]
    return 0


def _fmt(i: tuple[int, int]) -> str:
    f = lambda m: f"{m // 60:02d}:{m % 60:02d}"  # noqa: E731
    return f(i[0]) if i[0] == i[1] else f"{f(i[0])}-{f(i[1])}"


def _hedged(c: ClaimInfo) -> bool:
    return any(
        u.startswith("hedged wording") or u.startswith("imprecise time") for u in c.uncertainty
    )


def compare_pair(a: Member, b: Member) -> Comparison:
    ca, cb = a.claim, b.claim
    same_account = ca.evidence_id == cb.evidence_id and (
        not a.attribution or not b.attribution or a.attribution == b.attribution
    )
    if same_account:
        return Comparison(
            a,
            b,
            "same_account",
            None,
            "Both statements come from the same account, so they are not independent descriptions.",
        )
    if ca.interval is None or cb.interval is None:
        return Comparison(
            a,
            b,
            "missing_time",
            None,
            "At least one account gives no comparable time; this is missing "
            "information, not a disagreement.",
        )
    day = comparable(ca.date, cb.date)
    if day == "different_day":
        return Comparison(
            a,
            b,
            "different_day",
            None,
            f"The accounts state different dates ({ca.date} and {cb.date}); "
            "times of day are not compared across days.",
        )
    gap = _gap(ca.interval, cb.interval)
    times = f"'{ca.time_raw}' ({_fmt(ca.interval)}) and '{cb.time_raw}' ({_fmt(cb.interval)})"
    if gap == 0 and (ca.interval[0] != ca.interval[1] or cb.interval[0] != cb.interval[1]):
        return Comparison(
            a,
            b,
            "approximate_overlap",
            0,
            f"{times} overlap: at least one time is approximate, so they may "
            "describe the same moment.",
        )
    if gap <= TOLERANCE_MIN:
        return Comparison(
            a,
            b,
            "within_tolerance",
            gap,
            f"{times} differ by {gap} minutes, within the {TOLERANCE_MIN}-minute "
            "tolerance for independently recorded times.",
        )
    if gap <= ROUNDING_MIN and (_hedged(ca) or _hedged(cb)):
        return Comparison(
            a,
            b,
            "possible_rounding",
            gap,
            f"{times} differ by {gap} minutes and at least one account is "
            "hedged or approximate; rounding is a likely explanation.",
        )
    unknown_tz = not (ca.tz and cb.tz)
    if unknown_tz and gap % 60 <= 5 and 55 <= gap <= 14 * 60 + 5:
        return Comparison(
            a,
            b,
            "possible_timezone",
            gap,
            f"{times} differ by about {round(gap / 60)} hour(s) and no time zone "
            "is stated; a clock or time-zone difference could explain it.",
        )
    note = "" if day == "same_day" else " (at least one date is not stated)"
    return Comparison(
        a, b, "conflict_candidate", gap, f"{times} are at least {gap} minutes apart{note}."
    )


def compare_accounts(members: list[Member]) -> list[Comparison]:
    out: list[Comparison] = []
    for i, a in enumerate(members):
        for b in members[i + 1 :]:
            out.append(compare_pair(a, b))
    return out


def sequence_conflicts(
    events: list[tuple[str, str, str, str | None, list[Member]]],
) -> list[tuple[Member, Member, str]]:
    """Across CONFIRMED events with the same anchor and date: a step that normally comes
    first (dispatch, departure) reported later than a step that comes after it
    (arrival, delivery). Input tuples: (event_type, anchor_kind, anchor_key, date,
    members). Returns (earlier-step member, later-step member, explanation)."""
    out = []
    by_anchor: dict[tuple[str, str, str | None], list] = defaultdict(list)
    for etype, kind, key, date, members in events:
        if etype in SEQUENCE_ORDER and date:
            by_anchor[(kind, key, date)].append((etype, members))
    for (_k, key, date), items in by_anchor.items():
        for i, (ta, ma) in enumerate(items):
            for tb, mb in items[i + 1 :]:
                if SEQUENCE_ORDER[ta] == SEQUENCE_ORDER[tb]:
                    continue
                (first_t, first_m), (later_t, later_m) = sorted(
                    [(ta, ma), (tb, mb)], key=lambda x: SEQUENCE_ORDER[x[0]]
                )
                f_times = [m for m in first_m if m.claim.interval]
                l_times = [m for m in later_m if m.claim.interval]
                if not f_times or not l_times:
                    continue
                f = min(f_times, key=lambda m: m.claim.interval[0])
                lt = max(l_times, key=lambda m: m.claim.interval[1])
                if f.claim.interval[0] > lt.claim.interval[1] + TOLERANCE_MIN:
                    out.append(
                        (
                            f,
                            lt,
                            (
                                f"On {date}, the {first_t} of '{key}' is reported at "
                                f"{_fmt(f.claim.interval)}, after its {later_t} at "
                                f"{_fmt(lt.claim.interval)}; the usual order is {first_t} before "
                                f"{later_t}."
                            ),
                        )
                    )
    return out
