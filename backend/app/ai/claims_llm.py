"""Optional Gemini claim extractor (``CLAIM_EXTRACTOR=gemini`` + ``GEMINI_API_KEY``).

The model only proposes wording. Everything that matters for provenance is checked or
recomputed locally: the segment id must belong to the batch, the quote must occur in
that segment's text (the runner re-grounds it), times are re-read from the quote with
the same rules as the offline extractor, and entity mentions come from the quote only.
Evidence text is sent as JSON inside explicit data delimiters.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.ai.gemini_client import GeminiClient
from app.modules.analysis import extract
from app.modules.analysis.extract import ClaimDraft, SegmentView

PROMPT_VERSION = "claims_v1"
METHOD = f"gemini_{PROMPT_VERSION}"
BATCH_CHARS = 12_000
_PROMPT = (Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.txt").read_text("utf-8")


class LlmClaim(BaseModel):
    segment_id: str = Field(min_length=1, max_length=64)
    quote: str = Field(min_length=1, max_length=extract.MAX_QUOTE_CHARS)
    claim_text: str = Field(min_length=1, max_length=extract.MAX_QUOTE_CHARS)
    claim_type: Literal["date_time", "quantity", "location", "identity", "statement"]
    subject: str | None = Field(default=None, max_length=256)
    predicate: str | None = Field(default=None, max_length=128)
    object_value: str | None = Field(default=None, max_length=256)
    time_expression: str | None = Field(default=None, max_length=128)
    location: str | None = Field(default=None, max_length=256)
    is_inferred: bool = False
    confidence: float = Field(ge=0, le=1)
    uncertainty: list[str] = Field(default_factory=list, max_length=10)


class LlmClaims(BaseModel):
    claims: list[LlmClaim] = Field(max_length=200)


def segment_payload(segments: list[SegmentView]) -> str:
    """JSON-encoded evidence, with '<' escaped so data cannot close the delimiter."""
    items = [{"segment_id": s.id, "text": s.text or ""} for s in segments]
    return json.dumps(items, ensure_ascii=False).replace("<", "\\u003c")


def _batches(segments: list[SegmentView]) -> list[list[SegmentView]]:
    out: list[list[SegmentView]] = []
    current: list[SegmentView] = []
    size = 0
    for s in segments:
        n = len(s.text or "")
        if current and size + n > BATCH_CHARS:
            out.append(current)
            current, size = [], 0
        current.append(s)
        size += n
    if current:
        out.append(current)
    return out


class HybridClaimExtractor:
    """AI extraction with a per-evidence-item rule-based fallback.

    Each draft keeps the method that actually produced it, so fallback claims are
    labelled ``rule_based_v1`` and AI claims ``gemini_claims_v1``. Counters record how
    often the fallback was used and why (error types only, never evidence text).
    """

    method = "hybrid"

    def __init__(self, ai: GeminiClaimExtractor, rules: object) -> None:
        self._ai = ai
        self._rules = rules
        self.ai_items = 0
        self.fallback_items = 0
        self.fallback_reasons: dict[str, int] = {}

    def extract(self, segments: list[SegmentView]) -> list[ClaimDraft]:
        from app.ai.gemini_client import AIError

        try:
            drafts = self._ai.extract(segments)
            self.ai_items += 1
            return drafts
        except AIError as exc:
            self.fallback_items += 1
            name = type(exc).__name__
            self.fallback_reasons[name] = self.fallback_reasons.get(name, 0) + 1
            return self._rules.extract(segments)  # type: ignore[attr-defined]


class GeminiClaimExtractor:
    method = METHOD

    def __init__(self, client: GeminiClient) -> None:
        self._client = client

    def extract(self, segments: list[SegmentView]) -> list[ClaimDraft]:
        texty = [s for s in segments if (s.text or "").strip()]
        drafts: list[ClaimDraft] = []
        for batch in _batches(texty):
            by_id = {s.id: s for s in batch}
            user = (
                "Extract claims from these evidence segments.\n"
                f"<evidence_segments>\n{segment_payload(batch)}\n</evidence_segments>"
            )
            result = self._client.generate(_PROMPT, user, LlmClaims)  # raises on failure
            for item in result.claims:
                segment = by_id.get(item.segment_id)
                if segment is None:
                    continue  # the model named a segment it was not given
                drafts.append(self._draft(item, segment))
                if len(drafts) >= extract.MAX_CLAIMS_PER_EXTRACTION:
                    return drafts
        return drafts

    def _draft(self, item: LlmClaim, segment: SegmentView) -> ClaimDraft:
        text = segment.text or ""
        start = text.find(item.quote)
        times = extract.find_times(item.quote)
        dates = extract.find_dates(item.quote)
        event_time = None
        if times or dates:
            event_time = {k: v for k, v in (times or dates)[0].items() if k != "span"}
        elif item.time_expression:
            # Kept as written; never parsed into a precise value here.
            event_time = {
                "raw": item.time_expression,
                "kind": "model_reported",
                "precision": "unknown",
                "minutes": None,
                "range": None,
                "date_known": False,
            }
        predicate_label, predicate_key = extract.predicate_of(item.quote)
        uncertainty = [str(u)[:200] for u in item.uncertainty]
        if segment.segment_type == "transcript_segment":
            uncertainty.append("from machine transcription; not verified against the recording")
        elif segment.segment_type == "ocr_line":
            uncertainty.append("from OCR; characters may be misread")
        return ClaimDraft(
            segment_id=segment.id,
            claim_text=item.claim_text,
            claim_type=item.claim_type,
            quote=item.quote,
            quote_start=start if start >= 0 else None,
            quote_end=start + len(item.quote) if start >= 0 else None,
            locator=dict(segment.locator),
            modality=extract.MODALITY.get(segment.evidence_type, segment.evidence_type),
            subject=item.subject,
            predicate=item.predicate or predicate_label,
            predicate_key=predicate_key,
            object_value=item.object_value,
            event_time=event_time,
            location=item.location,
            uncertainty=uncertainty,
            source_engine_confidence=segment.engine_confidence,
            is_inferred=item.is_inferred,
            extraction_confidence=item.confidence,
            method=METHOD,
            mentions=extract.find_mentions(item.quote),
        )
