"""Shared wording helpers for reports: citations, a language guard, formatting."""

from __future__ import annotations

import html
import re
from typing import Any

# Generated (non-quoted) report text must never assert these. Evidence quotes are
# exempt: they are shown verbatim inside quotation marks.
BANNED = re.compile(
    r"\b(guilty|guilt of|innocent|lied|lying|liar|deceptive|deceived|deception detected|"
    r"proves?|proven|proof that|authentic(?:ated)?|genuine|forged|fraud(?:ulent)? (?:was|is) "
    r"committed|committed fraud|criminal|culprit|confess)\b",
    re.I,
)
DISCLAIMER = (
    "This report is an analytical aid produced by EvidenceX. It organises what the "
    "processed evidence says and where accounts appear to differ. It does not determine "
    "guilt, innocence, deception, authenticity or legal liability, and it does not "
    "establish objective truth. Machine-generated findings are proposals; only items "
    "marked as reviewed reflect a human decision. Confidence values are heuristic or "
    "model self-assessments, not statistically calibrated probabilities."
)


class LanguageGuardError(ValueError):
    pass


def guard(text: str) -> str:
    """Raise if generated text uses adjudicating language."""
    m = BANNED.search(text)
    if m:
        raise LanguageGuardError(f"generated text used disallowed wording: '{m.group(0)}'")
    return text


def esc(text: Any) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def hms(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    s = int(round(float(seconds)))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def cite(evidence_name: str, locator: dict[str, Any] | None) -> str:
    """Human-readable exact source reference."""
    loc = locator or {}
    kind = loc.get("kind")
    if kind == "pdf":
        where = f"page {loc.get('page')}"
        if loc.get("bbox"):
            x0, y0, x1, y1 = (round(float(v)) for v in loc["bbox"])
            where += f", region ({x0},{y0})–({x1},{y1}) pt"
    elif kind == "image":
        x0, y0, x1, y1 = (round(float(v)) for v in loc.get("bbox") or (0, 0, 0, 0))
        where = f"image region ({x0},{y0})–({x1},{y1}) px"
    elif kind == "audio":
        start = loc.get("word_start", loc.get("start"))
        end = loc.get("word_end", loc.get("end"))
        where = f"audio {hms(start)}–{hms(end)}"
    elif kind == "video":
        where = f"video frame at {hms(loc.get('t'))}"
        if loc.get("bbox"):
            where += " (text region)"
    elif kind == "csv":
        where = f"row {loc.get('row')}" + (f", column {loc['column']}" if loc.get("column") else "")
    elif kind == "xlsx":
        where = f"sheet '{loc.get('sheet')}', cells {loc.get('range')}"
    elif kind == "email":
        part = {
            "header": "header",
            "body_text": "body (plain text)",
            "body_html": "body (HTML as text)",
            "attachment": "attachment",
        }.get(str(loc.get("part")), str(loc.get("part")))
        where = f"email {part}" + (f" '{loc['name']}'" if loc.get("name") else "")
    else:
        where = "location not recorded"
    return f"{evidence_name}, {where}"


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"
