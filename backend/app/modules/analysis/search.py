"""Case-scoped evidence retrieval (pure ranking + DB loading).

Method ``lexical_bm25_v1``: BM25 keyword ranking over extracted segments, claims,
entities and events of ONE case, with
- light stemming ("arrived" ~ "arrive"),
- a small investigation-domain synonym table ("lorry" ~ "truck"), weighted lower,
- typo tolerance via character trigrams for words that do not match exactly,
- a bonus when the whole query appears verbatim.

It is NOT embedding-based semantic search: no embedding model is installed, and no
external embedding service is ever called. Every hit says which terms matched and
how, so results are explainable. The index is built from the database at query time,
so it always reflects current evidence (deleted items cannot appear).
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

METHOD = "lexical_bm25_v1"
METHOD_LABEL = (
    "Keyword ranking (BM25) with stemming, domain synonyms and typo tolerance. "
    "Not embedding-based; no external service is used."
)
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
STOP = set(
    "a an the of to in on at by for from and or is was were be been are it this that "
    "with as did does do what when where who which how why any there their its into "
    "about after before".split()
)
SYNONYMS: dict[str, set[str]] = {}
for group in [
    {"arrive", "arrival", "reach", "came", "enter", "entry"},
    {"depart", "departure", "left", "leave", "exit"},
    {"truck", "lorry", "vehicle", "van", "trailer"},
    {"shipment", "consignment", "parcel", "package", "cargo", "load"},
    {"delay", "late", "delayed", "overdue"},
    {"witness", "saw", "seen", "observ", "statement"},
    {"time", "hour", "clock", "timestamp"},
    {"payment", "invoice", "paid", "transfer", "money", "amount"},
    {"email", "message", "mail", "wrote"},
    {"camera", "cctv", "footage", "video"},
    {"receipt", "signed", "delivery"},
    {"missing", "lost", "absent", "gone"},
    {"conflict", "contradict", "inconsist", "disagree", "differ"},
]:
    for w in group:
        SYNONYMS[w] = group - {w}


def fold(text: str) -> str:
    """Lowercase and strip accents for matching only (stored text is never changed)."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def stem(word: str) -> str:
    for suf in ("ations", "ation", "ingly", "ing", "edly", "ed", "ies", "es", "s", "ly"):
        if len(word) > len(suf) + 2 and word.endswith(suf):
            return word[: -len(suf)] + ("y" if suf == "ies" else "")
    return word


def tokens(text: str) -> list[str]:
    return [stem(w) for w in _WORD.findall(fold(text)) if w not in STOP and len(w) > 1]


def _trigrams(w: str) -> set[str]:
    w = f"  {w} "
    return {w[i : i + 3] for i in range(len(w) - 2)}


def similarity(a: str, b: str) -> float:
    ta, tb = _trigrams(a), _trigrams(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


@dataclass
class Doc:
    kind: str
    id: str
    text: str
    title: str
    meta: dict[str, Any] = field(default_factory=dict)
    _tf: Counter | None = None
    _len: int = 0

    def prepare(self) -> None:
        toks = tokens(self.text + " " + self.title)
        self._tf, self._len = Counter(toks), len(toks)


@dataclass
class Hit:
    doc: Doc
    score: float
    matched: list[str]
    why: str


def expand(query: str) -> tuple[list[str], dict[str, tuple[str, float]]]:
    """Query terms and their expansions: term -> (reason, weight)."""
    base = tokens(query)
    expanded: dict[str, tuple[str, float]] = {t: ("exact", 1.0) for t in base}
    for t in base:
        for key, alts in SYNONYMS.items():
            if t == key or t.startswith(key):
                for alt in alts:
                    alt = stem(alt)
                    expanded.setdefault(alt, (f"synonym of '{t}'", 0.5))
    return base, expanded


def rank(docs: list[Doc], query: str, limit: int = 30) -> tuple[list[Hit], list[str]]:
    base, expanded = expand(query)
    if not base:
        return [], []
    for d in docs:
        if d._tf is None:
            d.prepare()
    n = len(docs) or 1
    avg = sum(d._len for d in docs) / n or 1.0
    vocab = {t for d in docs for t in d._tf}  # type: ignore[union-attr]
    # Typo tolerance: unseen query words map to close vocabulary words.
    for t in base:
        if t not in vocab and len(t) >= 4:
            close = sorted(
                ((similarity(t, v), v) for v in vocab if abs(len(v) - len(t)) <= 3), reverse=True
            )[:2]
            for s, v in close:
                if s >= 0.45:
                    expanded.setdefault(v, (f"close spelling of '{t}'", 0.4 * s))
    df = Counter(t for d in docs for t in set(d._tf) if t in expanded)  # type: ignore[arg-type]
    phrase = fold(query.strip())
    hits: list[Hit] = []
    for d in docs:
        score, matched, reasons = 0.0, [], []
        for t, (reason, w) in expanded.items():
            f = d._tf.get(t, 0)  # type: ignore[union-attr]
            if not f:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            score += w * idf * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * d._len / avg))
            matched.append(t)
            if reason != "exact":
                reasons.append(f"'{t}' ({reason})")
        if not matched:
            continue
        if len(phrase) > 4 and phrase in fold(d.text):
            score *= 1.5
            reasons.insert(0, "contains the exact phrase")
        exact = [t for t in matched if expanded[t][0] == "exact"]
        why = "Matched " + ", ".join(f"'{t}'" for t in exact) if exact else "Matched related terms"
        if reasons:
            why += "; also " + ", ".join(reasons)
        hits.append(Hit(d, round(score, 4), matched, why))
    hits.sort(key=lambda h: -h.score)
    return hits[:limit], sorted(expanded)


def excerpt(text: str, terms: list[str], width: int = 220) -> str:
    folded = fold(text)
    pos = min((folded.find(t) for t in terms if folded.find(t) >= 0), default=0)
    start = max(0, pos - width // 3)
    snippet = text[start : start + width]
    return ("…" if start else "") + snippet + ("…" if start + width < len(text) else "")
