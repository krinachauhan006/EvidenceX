"""Rule-based, source-grounded claim and entity extraction.

Pure functions of extracted segments: no database, no network, no model. Every claim
quotes its segment text verbatim (with character offsets) and inherits the segment's
locator, so it is always traceable. Nothing is corrected or normalized in the stored
text: "1030" stays "1030" (an ambiguous time format), "88,421" stays "88,421".

Deliberate limits (documented, tested):
- Free-text person and organization names are NOT extracted; they are too easy to
  confuse. People come only from structured email headers (address + display name).
- A sentence becomes a claim only when it carries a checkable feature (identifier,
  time, date, quantity, location, vehicle) or an explicit uncertainty statement.
  Ordinary prose is left alone rather than forced into a "fact".

Evidence text is data. Instructions inside it are matched like any other words and
never change what this code does.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

METHOD = "rule_based_v1"
MAX_CLAIMS_PER_EXTRACTION = 500
MAX_QUOTE_CHARS = 600

TEXT_SEGMENT_TYPES = frozenset(
    {
        "pdf_text_block",
        "ocr_line",
        "transcript_segment",
        "email_body_text",
        "email_body_html",
        "video_ocr_line",  # text read from a sampled video frame
    }
)
MODALITY = {
    "document": "pdf",
    "image": "image",
    "audio": "audio",
    "tabular": "tabular",
    "email": "email",
    "video": "video",
}

# --- patterns ------------------------------------------------------------------------

# Letters + digits, optionally followed by further "-PART" groups, so a compound record
# id such as "EX-004-EVE-001" stays ONE identifier instead of two unrelated ones.
_IDENT = re.compile(r"\b([A-Z]{1,4})[-\s]?(\d{3,8})((?:-[A-Z0-9]{1,8})*)\b")
_KEYED_NUMBER = re.compile(
    r"\b(shipment|consignment|order|waybill|tracking|invoice|container|parcel)\s+"
    r"(?:no\.?\s*|number\s*|#\s*)?(\d[\d,]{2,9})\b",
    re.IGNORECASE,
)
_SHIPMENT_WORDS = re.compile(r"\b(shipment|consignment|waybill|tracking|parcel|container)\b", re.I)
_TIME = re.compile(
    # HH:MM with optional :SS. The lookbehind stops a match from starting inside a longer
    # time ("12:15:00" must never yield "15:00"). A sentence-ending full stop may follow
    # ("at 10:30."); a further digit group may not.
    r"(?<![\d:.])\b([01]?\d|2[0-3])[:.]([0-5]\d)(?::([0-5]\d))?(?:\s*([ap])\.?m\.?)?"
    r"(?![\d:]|\.\d)",
    re.IGNORECASE,
)
_TIME_AMPM = re.compile(r"\b(1[0-2]|0?[1-9])\s*([ap])\.?m\.?\b", re.IGNORECASE)
_VAGUE_TIME = re.compile(
    r"\b(after noon|before noon|around noon|noon|midnight|midday|in the morning|"
    r"in the afternoon|in the evening|this morning|this afternoon|tonight|afternoon|"
    r"morning|evening)\b",
    re.IGNORECASE,
)
_FOUR_DIGIT_TIME = re.compile(
    r"\b(arrival|arrive[sd]?|depart(?:ure|ed|s)?|at|by|delivery|eta|etd)\s+(\d{4})\b",
    re.IGNORECASE,
)
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?\b")
_SLASH_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
_TEXT_DATE = re.compile(
    rf"\b(\d{{1,2}})\s+({_MONTHS})\.?,?\s+(\d{{4}})\b|\b({_MONTHS})\.?\s+(\d{{1,2}}),?\s+(\d{{4}})\b",
    re.IGNORECASE,
)
_QUANTITY = re.compile(
    r"\b(\d[\d,]*(?:\.\d+)?)\s*(kg|kilograms?|tonnes?|tons?|units?|pallets?|boxes|cartons?|"
    r"crates?|items?|pieces?|km|miles?|litres?|liters?|hours?|minutes?)\b",
    re.IGNORECASE,
)
_MONEY = re.compile(
    r"(?:[$€£])\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s?(?:usd|eur|gbp)\b", re.IGNORECASE
)
# The keyword is case-insensitive; the NAME after it is not (scoped "(?-i:...)"), so
# "Warehouse A" / "gate 4" match but "the site was" does not become a location.
_LOCATION = re.compile(
    # The name may not be the hour of a time ("entered gate 10:47" is not "gate 10").
    r"\b(warehouse|dock|gate|depot|bay|plant|site|terminal|yard|loading bay)\s+"
    r"(?-i:([A-Z0-9][\w-]*))\b(?![:.]\d)",
    re.IGNORECASE,
)
# A plate/fleet number must be upper case and contain a digit: "truck KA-01-4821" is a
# vehicle, "truck arrived" is not.
_VEHICLE = re.compile(
    r"\b(truck|van|vehicle|lorry|trailer|car)\s+(?:no\.?\s*|number\s*)?"
    r"(?-i:((?=[A-Z-]*\d)[A-Z0-9][A-Z0-9-]{2,}))\b",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_UNCERTAINTY = re.compile(
    r"\b(not certain|uncertain|uncertainty|not sure|unsure|i think|i believe|i guess|"
    r"may have|might|possibly|probably|perhaps|approximately|around|roughly|about|"
    r"recollection|i recall|recalls?|can't remember|cannot remember|don't remember|"
    r"unclear|may be|estimated?)\b",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")

_PREDICATES = (
    ("arrival", re.compile(r"\barriv(?:al|e|ed|es|ing)\b|\beta\b", re.I)),
    ("departure", re.compile(r"\bdepart(?:ure|ed|s)?\b|\bleft\b|\betd\b", re.I)),
    ("dispatch", re.compile(r"\bdispatch(?:ed)?\b|\bshipped\b", re.I)),
    ("delivery", re.compile(r"\bdeliver(?:y|ed|ies)?\b", re.I)),
    ("pickup", re.compile(r"\bpick(?:ed)?[- ]?up\b|\bcollect(?:ed|ion)\b", re.I)),
    ("loading", re.compile(r"\bload(?:ed|ing)?\b", re.I)),
    ("inspection", re.compile(r"\binspect(?:ed|ion)?\b", re.I)),
    ("assignment", re.compile(r"\bassign(?:ed|ment)?\b", re.I)),
)
_PLANNED = re.compile(r"\b(planned|scheduled|expected|estimated|eta|etd)\b", re.I)


@dataclass
class SegmentView:
    id: str
    segment_type: str
    text: str | None
    data: dict[str, Any] | None
    locator: dict[str, Any]
    engine_confidence: float | None
    evidence_type: str


@dataclass
class MentionDraft:
    text: str  # exact original string
    entity_type: str
    normalized_key: str
    display: str
    role: str | None = None


@dataclass
class ClaimDraft:
    segment_id: str | None
    claim_text: str
    claim_type: str
    quote: str
    quote_start: int | None
    quote_end: int | None
    locator: dict[str, Any] | None
    modality: str
    subject: str | None = None
    predicate: str | None = None
    predicate_key: str | None = None
    object_value: str | None = None
    event_time: dict[str, Any] | None = None
    location: str | None = None
    uncertainty: list[str] = field(default_factory=list)
    source_engine_confidence: float | None = None
    grounding: str = "grounded"
    is_inferred: bool = False
    extraction_confidence: float | None = None
    method: str = METHOD
    mentions: list[MentionDraft] = field(default_factory=list)

    def dedupe_key(self, evidence_id: str) -> str:
        raw = "|".join(
            str(part)
            for part in (
                evidence_id,
                self.segment_id,
                self.method,
                self.quote_start,
                self.quote_end,
                " ".join(self.claim_text.lower().split()),
            )
        )
        return hashlib.sha256(raw.encode()).hexdigest()


# --- normalization -----------------------------------------------------------------


def normalize_identifier(text: str) -> str:
    """Exact-match key: upper case, punctuation and spaces removed. NS-88421 -> NS88421."""
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def digits_of(text: str) -> str:
    return re.sub(r"\D", "", text)


def _minutes(hour: int, minute: int, ampm: str | None) -> int | None:
    if ampm:
        ampm = ampm.lower()
        if hour > 12:
            return None
        hour = hour % 12 + (12 if ampm == "p" else 0)
    return hour * 60 + minute


_VAGUE_RANGES = {
    "after noon": (12 * 60, 24 * 60 - 1),
    "afternoon": (12 * 60, 18 * 60),
    "in the afternoon": (12 * 60, 18 * 60),
    "this afternoon": (12 * 60, 18 * 60),
    "before noon": (0, 12 * 60),
    "morning": (5 * 60, 12 * 60),
    "in the morning": (5 * 60, 12 * 60),
    "this morning": (5 * 60, 12 * 60),
    "evening": (17 * 60, 23 * 60),
    "in the evening": (17 * 60, 23 * 60),
    "tonight": (18 * 60, 24 * 60 - 1),
    "noon": (11 * 60 + 45, 12 * 60 + 15),
    "midday": (11 * 60 + 45, 12 * 60 + 15),
    "around noon": (11 * 60 + 30, 12 * 60 + 30),
    "midnight": (0, 15),
}


def find_times(text: str) -> list[dict[str, Any]]:
    """Times as written, each with an explicit precision. Nothing is coerced."""
    found: list[dict[str, Any]] = []
    taken: list[tuple[int, int]] = []

    def free(span: tuple[int, int]) -> bool:
        return all(span[1] <= a or span[0] >= b for a, b in taken)

    for m in _TIME.finditer(text):
        minutes = _minutes(int(m.group(1)), int(m.group(2)), m.group(4))
        if minutes is None:
            continue
        found.append(
            {
                "raw": m.group(0).strip(),
                "kind": "time_of_day",
                "precision": "exact",
                "minutes": minutes,
                "range": None,
                "date_known": False,
                "span": m.span(),
            }
        )
        taken.append(m.span())
    for m in _TIME_AMPM.finditer(text):
        if free(m.span()):
            minutes = _minutes(int(m.group(1)), 0, m.group(2))
            found.append(
                {
                    "raw": m.group(0),
                    "kind": "time_of_day",
                    "precision": "exact",
                    "minutes": minutes,
                    "range": None,
                    "date_known": False,
                    "span": m.span(),
                }
            )
            taken.append(m.span())
    for m in _VAGUE_TIME.finditer(text):
        if free(m.span()):
            raw = m.group(0)
            rng = _VAGUE_RANGES.get(raw.lower())
            found.append(
                {
                    "raw": raw,
                    "kind": "vague",
                    "precision": "range",
                    "minutes": None,
                    "range": list(rng) if rng else None,
                    "date_known": False,
                    "span": m.span(),
                }
            )
            taken.append(m.span())
    for m in _FOUR_DIGIT_TIME.finditer(text):
        span = m.span(2)
        if free(span):
            # "1030" could be 10:30 or a number. Kept raw and marked ambiguous.
            found.append(
                {
                    "raw": m.group(2),
                    "kind": "ambiguous",
                    "precision": "unknown",
                    "minutes": None,
                    "range": None,
                    "date_known": False,
                    "span": span,
                    "note": "four digits; may be a time written without a colon",
                }
            )
            taken.append(span)
    return sorted(found, key=lambda t: t["span"][0])


def find_dates(text: str) -> list[dict[str, Any]]:
    found = []
    for m in _ISO_DATE.finditer(text):
        found.append(
            {
                "raw": m.group(0),
                "kind": "datetime" if m.group(4) else "date",
                "precision": "exact" if m.group(4) else "day",
                "value": m.group(0),
                "span": m.span(),
            }
        )
    for m in _SLASH_DATE.finditer(text):
        found.append(
            {
                "raw": m.group(0),
                "kind": "date",
                "precision": "day",
                "value": None,
                "span": m.span(),
                "note": "day/month order is ambiguous",
            }
        )
    for m in _TEXT_DATE.finditer(text):
        found.append(
            {"raw": m.group(0), "kind": "date", "precision": "day", "value": None, "span": m.span()}
        )
    return found


def _predicate(sentence: str) -> tuple[str | None, str | None]:
    for key, pattern in _PREDICATES:
        m = pattern.search(sentence)
        if m:
            planned = _PLANNED.search(sentence)
            label = f"{planned.group(0).lower()} {m.group(0).lower()}" if planned else m.group(0)
            return label.lower(), (f"planned_{key}" if planned else key)
    return None, None


def predicate_of(sentence: str) -> tuple[str | None, str | None]:
    """(label, normalized key) of the event a sentence describes, if any."""
    return _predicate(sentence)


def find_mentions(text: str) -> list[MentionDraft]:
    mentions: list[MentionDraft] = []
    seen: set[tuple[str, str]] = set()

    def add(m: MentionDraft) -> None:
        if (m.entity_type, m.normalized_key) not in seen and m.normalized_key:
            seen.add((m.entity_type, m.normalized_key))
            mentions.append(m)

    for m in _IDENT.finditer(text):
        window = text[max(0, m.start() - 40) : m.start()]
        etype = "shipment" if _SHIPMENT_WORDS.search(window) else "identifier"
        add(MentionDraft(m.group(0), etype, normalize_identifier(m.group(0)), m.group(0)))
    for m in _KEYED_NUMBER.finditer(text):
        digits = digits_of(m.group(2))
        if any(digits and digits in x.normalized_key for x in mentions):
            continue  # already captured with its prefix
        etype = "shipment" if _SHIPMENT_WORDS.search(m.group(1)) else "identifier"
        add(MentionDraft(m.group(0), etype, digits, f"{m.group(1).title()} {m.group(2)}"))
    for m in _VEHICLE.finditer(text):
        add(MentionDraft(m.group(0), "vehicle", normalize_identifier(m.group(2)), m.group(0)))
    for m in _LOCATION.finditer(text):
        add(MentionDraft(m.group(0), "location", normalize_identifier(m.group(0)), m.group(0)))
    for m in _EMAIL.finditer(text):
        add(MentionDraft(m.group(0), "contact", m.group(0).lower(), m.group(0)))
    return mentions


def _low_probability_words(segment: SegmentView) -> list[str]:
    data = segment.data or {}
    words = data.get("low_probability_words")
    return [w for w in words if isinstance(w, str)] if isinstance(words, list) else []


def _audio_locator(segment: SegmentView, start: int, end: int) -> dict[str, Any]:
    """Segment locator refined to the words covering [start, end) when available."""
    loc = dict(segment.locator)
    words = (segment.data or {}).get("words")
    text = segment.text or ""
    if not isinstance(words, list) or not words:
        return loc
    cursor, covered = 0, []
    for w in words:
        if not isinstance(w, dict) or not isinstance(w.get("word"), str):
            return loc
        idx = text.find(w["word"], cursor)
        if idx < 0:
            return loc  # text and words disagree: keep the segment-level locator
        cursor = idx + len(w["word"])
        if idx < end and cursor > start:
            covered.append(w)
    if covered:
        loc["word_start"] = covered[0].get("start")
        loc["word_end"] = covered[-1].get("end")
    return loc


# --- claims from text segments -----------------------------------------------------


def claims_from_text_segment(segment: SegmentView) -> list[ClaimDraft]:
    text = segment.text or ""
    modality = MODALITY.get(segment.evidence_type, segment.evidence_type)
    low_words = _low_probability_words(segment)
    drafts: list[ClaimDraft] = []
    for m in _SENTENCE.finditer(text):
        raw = m.group(0)
        lead = len(raw) - len(raw.lstrip())
        sentence = raw.strip()
        if len(sentence) < 3:
            continue
        start = m.start() + lead
        end = start + len(sentence)
        times, dates = find_times(sentence), find_dates(sentence)
        mentions = find_mentions(sentence)
        quantities = [q.group(0) for q in _QUANTITY.finditer(sentence)]
        quantities += [q.group(0) for q in _MONEY.finditer(sentence)]
        hedges = sorted({h.group(0).lower() for h in _UNCERTAINTY.finditer(sentence)})
        locations = [x for x in mentions if x.entity_type == "location"]
        if not (times or dates or mentions or quantities or hedges):
            continue
        if hedges and not (times or dates or mentions or quantities):
            # A bare hedge only counts in first-person accounts (statements, emails).
            if modality not in ("audio", "email", "pdf") and segment.segment_type != "ocr_line":
                continue
        predicate, predicate_key = _predicate(sentence)
        event_time = None
        if times or dates:
            first = (times or dates)[0]
            event_time = {k: v for k, v in first.items() if k != "span"}
            if dates and times:
                event_time["date_raw"] = dates[0]["raw"]
                event_time["date_known"] = True
        if times or dates:
            claim_type = "date_time"
        elif quantities:
            claim_type = "quantity"
        elif locations:
            claim_type = "location"
        elif mentions:
            claim_type = "identity"
        else:
            claim_type = "statement"
        uncertainty = [f"hedged wording: {h}" for h in hedges]
        flagged = [w for w in low_words if w in sentence]
        if flagged:
            uncertainty.append("engine flagged possibly misheard words: " + ", ".join(flagged))
        for t in times:
            if t["precision"] != "exact":
                uncertainty.append(f"imprecise time '{t['raw']}' ({t['precision']})")
        for d in dates:
            if d.get("note"):
                uncertainty.append(f"date '{d['raw']}': {d['note']}")
        if segment.segment_type == "transcript_segment":
            uncertainty.append("from machine transcription; not verified against the recording")
        elif segment.segment_type == "ocr_line":
            uncertainty.append("from OCR; characters may be misread")
        elif segment.segment_type == "video_ocr_line":
            uncertainty.append("from OCR of a sampled video frame; characters may be misread")
        subject = next(
            (x.text for x in mentions if x.entity_type in ("shipment", "identifier", "vehicle")),
            None,
        )
        locator = (
            _audio_locator(segment, start, end)
            if segment.locator.get("kind") == "audio"
            else dict(segment.locator)
        )
        drafts.append(
            ClaimDraft(
                segment_id=segment.id,
                claim_text=sentence[:MAX_QUOTE_CHARS],
                claim_type=claim_type,
                quote=text[start:end][:MAX_QUOTE_CHARS],
                quote_start=start,
                quote_end=min(end, start + MAX_QUOTE_CHARS),
                locator=locator,
                modality=modality,
                subject=subject,
                predicate=predicate,
                predicate_key=predicate_key,
                object_value=(times or dates)[0]["raw"]
                if (times or dates)
                else (quantities[0] if quantities else None),
                event_time=event_time,
                location=locations[0].text if locations else None,
                uncertainty=uncertainty,
                source_engine_confidence=segment.engine_confidence,
                mentions=mentions,
            )
        )
    return drafts


# --- claims from structured segments -----------------------------------------------


def _column_predicate(column: str) -> tuple[str | None, str | None]:
    label = column.replace("_", " ").strip()
    _, key = _predicate(label)
    return label.lower(), key


def claims_from_table_row(segment: SegmentView) -> list[ClaimDraft]:
    cells = (segment.data or {}).get("cells")
    if not isinstance(cells, list) or not cells:
        return []
    mentions: list[MentionDraft] = []
    event_time = None
    predicate = predicate_key = None
    quantity = None
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        value = cell.get("value")
        column = str(cell.get("column") or "")
        if value is None or value == "":
            continue
        sval = str(value)
        col_label = column.replace("_", " ")
        found = find_mentions(sval)
        if _SHIPMENT_WORDS.search(col_label):
            # The column header gives the context the cell value alone lacks.
            for x in found:
                if x.entity_type == "identifier":
                    x.entity_type = "shipment"
        mentions += [x for x in found if x not in mentions]
        if column and _SHIPMENT_WORDS.search(col_label) and not found:
            digits = digits_of(sval)
            if len(digits) >= 3 and len(digits) == len(sval.replace(",", "").strip()):
                mentions.append(MentionDraft(sval, "shipment", digits, f"Shipment {sval}"))
        hint = cell.get("type_hint")
        if event_time is None:
            if hint in ("date", "datetime", "time"):
                event_time = {
                    "raw": sval,
                    "kind": hint,
                    "precision": "exact" if hint != "date" else "day",
                    "value": sval,
                    "column": column,
                    "coord": cell.get("coord"),
                    "minutes": _iso_minutes(sval) if hint != "date" else None,
                    "range": None,
                    "date_known": hint != "time",
                }
            else:
                times = find_times(sval)
                if times and _column_predicate(column)[1]:
                    t = {k: v for k, v in times[0].items() if k != "span"}
                    event_time = {**t, "column": column, "coord": cell.get("coord")}
            if event_time is not None:
                predicate, predicate_key = _column_predicate(column)
        if quantity is None and hint in ("integer", "decimal") and _QUANTITY_COL.search(column):
            quantity = f"{column}: {sval}"
    if not (mentions or event_time or quantity):
        return []
    text = segment.text or ""
    locator = dict(segment.locator)
    if event_time and event_time.get("column"):
        locator["column"] = event_time["column"]
        if event_time.get("coord"):
            locator["cell"] = event_time["coord"]
    return [
        ClaimDraft(
            segment_id=segment.id,
            claim_text=text[:MAX_QUOTE_CHARS] or "(row without text)",
            claim_type="date_time" if event_time else ("quantity" if quantity else "record"),
            quote=text[:MAX_QUOTE_CHARS],
            quote_start=0,
            quote_end=min(len(text), MAX_QUOTE_CHARS),
            locator=locator,
            modality="tabular",
            subject=next(
                (
                    x.text
                    for x in mentions
                    if x.entity_type in ("shipment", "identifier", "vehicle")
                ),
                None,
            ),
            predicate=predicate,
            predicate_key=predicate_key,
            object_value=event_time["raw"] if event_time else quantity,
            event_time=event_time,
            mentions=mentions,
        )
    ]


_QUANTITY_COL = re.compile(r"\b(qty|quantity|count|weight|units|pallets|boxes|amount)\b", re.I)


def _iso_minutes(value: str) -> int | None:
    m = re.search(r"(?:T|\s|^)(\d{2}):(\d{2})", value)
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def claims_from_email_header(segment: SegmentView) -> list[ClaimDraft]:
    data = segment.data or {}
    name = str(segment.locator.get("name") or "")
    text = segment.text or ""
    mentions = []
    for addr in data.get("addresses") or []:
        if isinstance(addr, dict) and addr.get("address"):
            display = addr.get("display_name") or addr["address"]
            mentions.append(
                MentionDraft(
                    addr["address"], "contact", addr["address"].lower(), display, role=name.lower()
                )
            )
    if name.lower() == "date":
        iso = data.get("date_iso")
        return [
            ClaimDraft(
                segment_id=segment.id,
                claim_text=f"The message is dated: {text}",
                claim_type="date_time",
                quote=text,
                quote_start=0,
                quote_end=len(text),
                locator=dict(segment.locator),
                modality="email",
                predicate="sent",
                predicate_key="email_sent",
                object_value=text,
                event_time={
                    "raw": text,
                    "kind": "datetime",
                    "value": iso,
                    "precision": "exact" if iso else "unknown",
                    "tz_known": data.get("tz_known"),
                    "minutes": None,
                    "range": None,
                    "date_known": iso is not None,
                },
                uncertainty=[] if iso else ["the Date header did not parse"],
            )
        ]
    if name.lower() in ("from", "to", "cc") and mentions:
        return [
            ClaimDraft(
                segment_id=segment.id,
                claim_text=f"{name}: {text}",
                claim_type="identity",
                quote=text,
                quote_start=0,
                quote_end=len(text),
                locator=dict(segment.locator),
                modality="email",
                predicate=name.lower(),
                predicate_key=f"email_{name.lower()}",
                object_value=text,
                mentions=mentions,
            )
        ]
    return []


def extract_claims(segments: Iterable[SegmentView]) -> list[ClaimDraft]:
    """All claims for one extraction run, in source order, capped."""
    out: list[ClaimDraft] = []
    for segment in segments:
        if segment.segment_type in TEXT_SEGMENT_TYPES:
            out += claims_from_text_segment(segment)
        elif segment.segment_type == "table_row":
            out += claims_from_table_row(segment)
        elif segment.segment_type == "email_header":
            out += claims_from_email_header(segment)
        if len(out) >= MAX_CLAIMS_PER_EXTRACTION:
            return out[:MAX_CLAIMS_PER_EXTRACTION]
    return out


# --- entity resolution candidates --------------------------------------------------


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


IDENTIFIER_TYPES = frozenset({"shipment", "identifier", "vehicle"})


_SIMPLE_KEY = re.compile(r"[A-Z]*\d+")


def resolution_candidate(
    a: tuple[str, str], b: tuple[str, str], *, misreading_possible: bool = True
) -> str | None:
    """Why two entity keys (type, key) MAY be the same thing, or None.

    Never used to merge automatically. People/contacts are only ever matched on an
    identical address, which is handled by the exact key, so they never appear here.

    Digit comparisons apply only to simple keys (letters then digits, e.g. NS88421).
    Compound record ids (EX004EVE001) are only related when identical: their digits
    come from several parts and sharing them says nothing. The one-digit "possible
    misreading" rule needs ``misreading_possible`` (one side read by OCR or speech
    recognition); typed records like EVE-001 / EVE-002 are distinct sequential ids.
    """
    (type_a, key_a), (type_b, key_b) = a, b
    if key_a == key_b and type_a == type_b:
        return None
    if type_a not in IDENTIFIER_TYPES or type_b not in IDENTIFIER_TYPES:
        return None
    if key_a == key_b:
        return "the same characters were recorded as different entity types"
    if not (_SIMPLE_KEY.fullmatch(key_a) and _SIMPLE_KEY.fullmatch(key_b)):
        return None
    digits_a, digits_b = digits_of(key_a), digits_of(key_b)
    if len(digits_a) < 3 or len(digits_b) < 3:
        return None
    prefix_a, prefix_b = key_a[: -len(digits_a)], key_b[: -len(digits_b)]
    # Two different explicit prefixes (CP001 / ENT001, INV771 / PO771) usually name
    # different record series that reuse short running numbers.
    distinct_series = bool(prefix_a and prefix_b and prefix_a != prefix_b)
    if digits_a == digits_b:
        if distinct_series and len(digits_a) < 4:
            return None
        return f"the same digits ({digits_a}) appear with different prefixes or none"
    if (
        misreading_possible
        and not distinct_series
        and abs(len(digits_a) - len(digits_b)) <= 1
        and _edit_distance(digits_a, digits_b) == 1
    ):
        return f"the digits differ by one character ({digits_a} vs {digits_b}); possible misreading"
    return None


# Candidate tiers, strongest first. The score is a heuristic ordering aid for
# reviewers, not a probability that the two records are the same thing.
CANDIDATE_TIERS = ("exact", "strong", "weak", "conflicting")
_TIER_SCORE = {"exact": 0.9, "strong": 0.7, "weak": 0.4, "conflicting": 0.3}


def _name_key(name: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", name.lower()).split())


def assess_candidate(
    a: tuple[str, str, str],
    b: tuple[str, str, str],
    *,
    misreading_possible: bool = True,
) -> dict[str, Any] | None:
    """Tier, heuristic score and the factors for and against two records (type, key,
    display name) being the same thing, or None when nothing links them.

    - exact: identical characters recorded under different identifier types;
    - strong: the same digits with different or missing prefixes;
    - weak: one differing digit where OCR/speech could have misread it;
    - conflicting: signals point both ways (the same contact name with different
      addresses; the same long number in two different record series).
    Never used to merge automatically.
    """
    (type_a, key_a, name_a), (type_b, key_b, name_b) = a, b
    factors: list[dict[str, Any]] = []
    if type_a == type_b == "contact" and key_a != key_b:
        na, nb = _name_key(name_a), _name_key(name_b)
        if na and na == nb and "@" not in name_a + name_b and len(na) >= 4:
            factors = [
                {"factor": "same display name", "effect": "+", "detail": name_a},
                {
                    "factor": "different addresses",
                    "effect": "-",
                    "detail": f"{key_a} vs {key_b}; different people can share a name",
                },
            ]
            return {
                "tier": "conflicting",
                "score": _TIER_SCORE["conflicting"],
                "reason": "the same name is used with different email addresses",
                "factors": factors,
            }
        return None
    reason = resolution_candidate(
        (type_a, key_a), (type_b, key_b), misreading_possible=misreading_possible
    )
    if reason is None:
        return None
    if key_a == key_b:
        tier = "exact"
        factors = [
            {"factor": "identical characters", "effect": "+", "detail": key_a},
            {"factor": "different entity types", "effect": "-", "detail": f"{type_a} / {type_b}"},
        ]
    elif reason.startswith("the same digits"):
        digits = digits_of(key_a)
        pa, pb = key_a[: -len(digits)], key_b[: -len(digits)]
        factors = [{"factor": "same digits", "effect": "+", "detail": digits}]
        if pa and pb and pa != pb:
            tier = "conflicting"
            factors.append(
                {
                    "factor": "different record series",
                    "effect": "-",
                    "detail": f"prefixes {pa} and {pb} usually name different series",
                }
            )
        else:
            tier = "strong"
            factors.append(
                {
                    "factor": "prefix missing on one side",
                    "effect": "+",
                    "detail": f"{key_a} / {key_b}",
                }
            )
    else:
        tier = "weak"
        factors = [
            {"factor": "one digit differs", "effect": "+", "detail": f"{key_a} vs {key_b}"},
            {
                "factor": "machine-read source",
                "effect": "+",
                "detail": "OCR or speech recognition can misread single characters",
            },
            {
                "factor": "different numbers",
                "effect": "-",
                "detail": "sequential or similar ids often belong to different records",
            },
        ]
    return {"tier": tier, "score": _TIER_SCORE[tier], "reason": reason, "factors": factors}
