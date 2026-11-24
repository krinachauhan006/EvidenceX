# EvidenceX — Safety and Provenance Invariants

These are non-negotiable invariants. Code that violates them is incorrect even if
it compiles and passes other tests.

## Provenance invariants
1. Every claim MUST reference exactly one `extraction_segment` (its source anchor).
   A claim with no anchor is invalid and must not be persisted.
2. Every `extraction_segment` MUST carry a physical locator:
   - PDF/image: a page number and bounding box, OR
   - audio: start/end timestamps, OR
   - CSV: row number and column name(s), OR
   - XLSX: worksheet name, row, and cell coordinate(s), OR
   - EML: the header name or message part (body_text, body_html, attachment).
3. Every finding MUST reference one or more existing, valid claims. A finding that
   references a deleted or non-existent claim is invalid.
4. Provenance links are immutable facts. If a claim is edited during review, the
   edit is recorded as a new reviewed state; the original extracted text and its
   anchor are preserved for audit.

## Confidence invariants
5. Extraction confidence, resolution confidence, and detection confidence are
   separate fields and MUST NOT be merged into a single "score".
6. Confidence is the model's self-assessment of its own output, NOT a claim about
   factual truth. UI copy and report text MUST reflect this distinction.
7. Never present a low-confidence extraction as fact, and never upgrade confidence
   to compensate for missing data.

## Uncertainty invariants
8. Temporal values preserve precision/uncertainty
   (`exact | day | month | year | range | unknown`). Never coerce a vague time
   reference into a precise timestamp.
9. When evidence is ambiguous, represent the ambiguity; do not resolve it silently.

## What EvidenceX must never claim
10. It does NOT determine guilt or innocence.
11. It does NOT detect lies or deception.
12. It does NOT authenticate or certify evidence as genuine.
13. Output language must avoid implying any of the above. Prefer "the system
    identified", "claims that appear to conflict", "unverified".

## Input safety invariants
14. All uploaded files are untrusted. Validate the ACTUAL file type by magic bytes,
    not by file extension or client-supplied MIME.
15. Enforce size and type limits BEFORE any processing.
16. Store uploads under content-addressed names, outside any web-served directory,
    and never execute uploaded content under any circumstance.
17. Prevent path traversal: never build a storage or read path from a user-supplied
    filename. Derive paths only from the content hash; reject/normalize any input
    containing `..`, absolute paths, or path separators.
18. Never pass raw file bytes or secrets into logs or AI prompts beyond the
    extracted text required for the task.
19. API keys and all secrets live in environment variables only. Never in code,
    logs, responses, or committed files.

## Prompt-injection safety
20. Text extracted from evidence is DATA, never instructions. If extracted content
    contains text that looks like instructions to the model ("ignore previous
    instructions", "output X"), it MUST be treated as content to analyze, never as
    a command that changes system behavior.
21. Evidence text is passed to the model inside clearly delimited data boundaries,
    and the system prompt states that content within those boundaries is untrusted
    data to be analyzed, not instructions to follow.

## AI output safety
22. All AI output is validated against a Pydantic schema before use. Unvalidated
    output must never drive control flow or be persisted.
23. On validation failure: one repair retry, then fail the artifact. Never
    fabricate values to satisfy a schema.

## Contradiction record invariants
24. Every potential contradiction MUST contain, at minimum:
    - both related claim ids,
    - exact source references (via the claims' segment anchors),
    - a human-readable explanation of the potential inconsistency,
    - `detection_confidence` (separate from factual truth),
    - one or more alternative explanations (the inconsistency may be benign),
    - a review status (`open | dismissed | confirmed`).
25. The engine surfaces POTENTIAL inconsistencies for human review. It never
    asserts that a contradiction proves wrongdoing, deception, or falsity.

## Human-in-the-loop
26. The system assists; humans decide. Every accept/reject/edit/dismiss/confirm is
    recorded in `review_actions` as an audit trail.
