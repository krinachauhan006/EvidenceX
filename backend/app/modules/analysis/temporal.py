"""Temporal normalization v2 (pure functions).

Dates are attached to times so that accounts of different days are never compared as
if they were the same day. Nothing gains precision it did not have:

- a date written in the sentence -> precision ``day`` (source ``sentence``);
- an email's own Date header -> ``day`` (source ``email_header``), with the offset;
- exactly ONE distinct date anywhere in the same evidence item -> ``inherited_day``
  (source ``document``); several dates in the document -> no inheritance;
- an ambiguous slash date (03/04/2026) -> ``ambiguous`` with both readings, never
  resolved;
- otherwise ``unknown``.

Inheritance never crosses evidence items.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_TEXT_DMY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b")
_TEXT_MDY = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b")
_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")


def _valid(y: int, m: int, d: int) -> str | None:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


@dataclass
class DateReading:
    value: str | None  # YYYY-MM-DD when unambiguous
    precision: str  # day | inherited_day | ambiguous | unknown
    source: str | None  # sentence | email_header | document
    raw: str | None = None
    alternatives: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "date": self.value,
            "date_precision": self.precision,
            "date_source": self.source,
            "date_raw": self.raw,
            "date_alternatives": list(self.alternatives),
        }


def dates_in(text: str) -> list[DateReading]:
    """Every date written in ``text``, in order, as readings with source 'sentence'."""
    found: list[tuple[int, DateReading]] = []
    for m in _ISO.finditer(text):
        v = _valid(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if v:
            found.append((m.start(), DateReading(v, "day", "sentence", m.group(0))))
    for m in _TEXT_DMY.finditer(text):
        month = _MONTHS.get(m.group(2).lower())
        v = month and _valid(int(m.group(3)), month, int(m.group(1)))
        if v:
            found.append((m.start(), DateReading(v, "day", "sentence", m.group(0))))
    for m in _TEXT_MDY.finditer(text):
        month = _MONTHS.get(m.group(1).lower())
        v = month and _valid(int(m.group(3)), month, int(m.group(2)))
        if v:
            found.append((m.start(), DateReading(v, "day", "sentence", m.group(0))))
    for m in _SLASH.finditer(text):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        dmy, mdy = _valid(y, b, a), _valid(y, a, b)
        options = sorted({x for x in (dmy, mdy) if x})
        if len(options) == 1:
            found.append((m.start(), DateReading(options[0], "day", "sentence", m.group(0))))
        elif options:
            found.append(
                (m.start(), DateReading(None, "ambiguous", "sentence", m.group(0), options))
            )
    found.sort(key=lambda x: x[0])
    seen, out = set(), []
    for _pos, r in found:  # one reading per written date
        key = (r.raw, r.value)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def document_date(texts: list[str]) -> str | None:
    """The single distinct unambiguous date of a document, else None."""
    values = {r.value for t in texts for r in dates_in(t or "") if r.value}
    return next(iter(values)) if len(values) == 1 else None


def claim_date(
    quote: str,
    *,
    email_date_iso: str | None = None,
    doc_date: str | None = None,
) -> DateReading:
    """The date a claim's time refers to, with an honest precision label."""
    in_sentence = dates_in(quote)
    if in_sentence:
        return in_sentence[0]
    if email_date_iso:
        v = email_date_iso[:10]
        if _valid(*(int(x) for x in v.split("-"))):
            return DateReading(v, "day", "email_header", email_date_iso)
    if doc_date:
        return DateReading(doc_date, "inherited_day", "document", None)
    return DateReading(None, "unknown", None)


def comparable(a: str | None, b: str | None) -> str:
    """same_day | different_day | unknown_day."""
    if a and b:
        return "same_day" if a == b else "different_day"
    return "unknown_day"


def tz_of(event_time: dict[str, Any] | None) -> str | None:
    """A stated UTC offset ('+05:30'), if the source carried one."""
    raw = str((event_time or {}).get("value") or "")
    m = re.search(r"([+-]\d{2}:\d{2}|Z)$", raw)
    return m.group(1) if m else None
