# Phase 1 — Analysis, review and investigation workspace

Status: implemented, tested and browser-verified. Migrations `0005_create_analysis` and
`0006_analysis_not_null_ts` are applied to `backend/var/evidencex.db` (backups in
`backups/db/`). Analysis has been run on "Missing Shipment Investigation" and on the
clearly labelled synthetic case "EvidenceX Synthetic Demo — Contradiction Review".

## Layers (never mixed)
1. **Original evidence** — `evidence` row + content-addressed blob. Immutable.
2. **Extracted content** — `extractions` / `extraction_segments`. Append-only, never edited.
3. **Machine findings** — `claims`, `entities`, `claim_entities`, `claim_relationships`,
   `contradictions`, `alternative_explanations`. They point back to (2) and (1) by id.
4. **Human decisions** — review columns on (3), `segment_reviews` for transcript
   corrections, and the append-only `review_actions` audit trail.

## Module layout
`backend/app/modules/analysis/`
- `extract.py` — pure, rule-based claim + mention extraction (`rule_based_v1`).
- `engine.py` — pure contradiction engine (temporal, quantity) + alternative explanations.
- `runner.py` — background case analysis (own session, per-item savepoint, idempotent).
- `repository.py`, `service.py`, `router.py`, `schemas.py`, `models.py`.
`backend/app/ai/` — `gemini_client.py` (stdlib HTTP, schema validation, one repair),
`claims_llm.py`, `prompts/claims_v1.txt`. Off by default.
`backend/app/modules/processing/audio_models.py` — local speech-model discovery.
`backend/app/modules/evidence/preview.py` — PDF page PNG rendering.

## Schema (migration 0005)
| table | purpose |
|---|---|
| analysis_runs | one case-level pass; status running/completed/failed; stats JSON |
| claims | quote (verbatim) + offsets + locator + segment_id anchor; claim_type, subject, predicate, predicate_key, object_value, event_time JSON (raw + precision), location, modality, grounding, extraction_method, is_inferred, extraction_confidence (LLM only), source_engine_confidence (OCR/ASR), uncertainty[], review_status, reviewed_text, review_note, reviewed_by/at, dedupe_key (unique per case) |
| entities | entity_type, display_name, normalized_key (exact-match), aliases, resolution_status (unresolved/confirmed/merged/rejected), merged_into_id |
| claim_entities | mention: exact original string in a claim -> entity |
| claim_relationships | mentions_same_entity / potentially_conflicts_with between claims of different evidence |
| contradictions | claim_a/claim_b, category, explanation {first_states, second_states, why, uncertain, would_resolve}, severity, detection_confidence, uncertainty, review_status, resolution_note, linked_evidence_ids |
| alternative_explanations | explanation, supporting/weakening evidence, missing info, verification recommendation, basis (source_supported / machine_hypothesis / human) |
| review_actions | append-only audit: target, action, from/to status, note, payload, reviewer, time |
| segment_reviews | append-only human corrections of a segment's text (newest = current) |

All tables are case-scoped and cascade from `cases`.

## Methodology
**Claims (rule_based_v1).** Text segments are split into sentences. A sentence becomes a
claim only if it has a checkable feature (identifier, time, date, quantity, location,
vehicle, email address) or an explicit hedge. The quote is the exact sentence with
offsets. Table rows become one claim each when they contain an identifier, time or
quantity column. Email `Date` / `From` / `To` / `Cc` headers become claims. Audio claims
inherit word-level times (`word_start`/`word_end`) when word data matches. Uncertainty
notes: hedged wording, low-probability words, imprecise times, ambiguous dates, machine
transcription, OCR. Rule-based claims have `extraction_confidence = null`.

**Times.** Stored as written with explicit precision: `exact` (10:30, 10:30:00, 2:15 pm),
`range` (after noon -> 12:00–23:59), `unknown` ("arrival 1030" — ambiguous, never
interpreted). A match may not start inside a longer time, so "12:15:00" is read as 12:15,
never as "15:00".

**Mention patterns.** Identifiers keep compound record ids whole ("EX-004-EVE-001" is one
identifier). Vehicle plates must be upper case and contain a digit ("truck KA-01-4821";
"truck arrived" is not a vehicle). Location names after a keyword are case-sensitive and
may not be the hour of a time ("Warehouse A", "gate 4"; not "the site was", not
"gate 10:47").

**Entities.** Only identical `normalized_key` values share a record (NS-88421 == NS88421).
Identifier-like mentions (shipment/identifier) share by key across contexts. People are
NOT extracted from free text; contacts come only from email headers keyed by address.
Near matches are listed as **candidates** for a reviewer and never merged automatically.
Rules apply only to simple keys (letters then digits): the same digits with a missing
prefix, or with different prefixes when the number has 4+ digits; and a one-digit
difference only under the same (or no) prefix AND when one side was machine-read
(audio or image), since typed sequential ids such as EVE-001 / EVE-002 are distinct.

**Relationships.** One `mentions_same_entity` link per claim pair, even when the two
claims share several entities (the runner tracks pairs within a pass because the session
does not autoflush). The rationale names the entity type ("the same location 'Warehouse A'").

**Potential contradictions.** Proposed only when two claims come from different
evidence items, mention the same (canonical) entity, and share the same `predicate_key`.
- Temporal: interval gap > 10 minutes. Ambiguous values are never compared; vague ranges
  are compared as ranges (overlap = no conflict).
- Quantity: same unit, different number.
- Location conflicts are NOT detected (deliberately, to avoid false positives).
- `detection_confidence` is a heuristic (base 0.7, lowered for audio/OCR/hedging/
  imprecision; clamped 0.1–0.9). It is not a probability that either source is wrong.
- Every record gets template alternative explanations labelled `machine_hypothesis`.

**Gemini path (optional).** Evidence text is JSON-encoded inside `<evidence_segments>`
delimiters with `<` escaped; the system prompt marks it as untrusted data. Output is
validated by Pydantic; one repair retry; then the item fails (no fabricated values).
Unknown segment ids are dropped; quotes are re-grounded; times and mentions are re-read
locally from the quote.

## Review workflow
- Claims and relationships: `unreviewed -> verified | needs_verification | rejected`;
  `needs_verification -> verified | rejected`; `verified | rejected -> needs_verification`.
  `edit` stores `reviewed_text` (claim_text and quote never change). `note` adds a note.
- Contradictions: `unreviewed -> confirmed | unresolved | rejected`;
  `unresolved -> confirmed | resolved | rejected`; `confirmed -> resolved | unresolved`;
  `rejected -> unresolved`; `resolved -> unresolved`. `resolve` requires a note.
  `link_evidence` (same case only), `add_alternative` (basis = human).
  "Confirmed" means a reviewer agrees the sources disagree — not which one is right.
- Entities: `confirm`, `reject`, `merge` (into target; mentions untouched), `unmerge`,
  `mark_distinct` (suppresses the candidate pair), `note`.
- Transcript/segment corrections: `POST .../segments/{id}/reviews`; machine text is kept.
- Every action writes a `review_actions` row. Invalid transitions return 409.

## API (all under `/api/cases/{case_id}` unless noted)
`POST /analysis` (202, 409 if one is running), `GET /analysis/latest`,
`GET /claims`, `GET /claims/{id}`, `POST /claims/{id}/review`,
`GET /entities`, `GET /entities/candidates`, `GET /entities/{id}`, `POST /entities/{id}/review`,
`GET /relationships`, `POST /relationships/{id}/review`,
`GET /contradictions`, `GET /contradictions/{id}`, `POST /contradictions/{id}/review`,
`POST /contradictions/{id}/alternatives`, `GET /review-queue`, `GET /reviews`,
`GET|POST /evidence/{eid}/segments/{sid}/reviews`, `GET /graph`, `GET /dashboard`,
`GET /evidence/{eid}/analysis-summary`, `GET /evidence/{eid}/pages/{n}/image?dpi=`
(PDF only, DPI 24–150), and `GET /api/audio/models`. `POST /evidence/{eid}/process`
accepts `audio_model` (must be available locally; 400 otherwise; never substituted).

## Frontend
Case shell with nav: Overview (dashboard) / Evidence / Claims / Entities /
Contradictions / Graph / Review queue. Evidence workspace at
`/cases/{id}/evidence/{eid}` with header, summary tiles and tabs (Overview, Original
preview, Extracted content, Claims, Entities, Relationships, Processing details, Run
history). Viewers: PDF (rendered pages, thumbnails, per-page text, bbox overlays), image
(original + OCR boxes + confidence), table (sheets, row numbers, formula vs cached value,
pagination), email (headers, text vs HTML-as-text, attachments metadata-only), audio
(player, segments, low-probability words, corrections). Claim -> source navigation via
`?tab=preview&segment=…&page=…&t=…`. Knowledge graph: custom SVG + deterministic force
layout (no graph library), zoom/pan/select/search/filters/legend/side panel.

Empty states (`components/analysis/analysis-state.ts`) distinguish: status not loaded,
never analysed, running, failed, completed with zero, and completed-but-filtered, for
Claims, Contradictions, Review queue, Entities and Graph. A zero is never shown as green
or "all clear". The dashboard `main` column is `min-w-0` so long quotes cannot overflow
narrow screens (verified at 700 px).

## Limitations
- Rule-based extraction misses claims without the listed features and does not extract
  person/organisation names from free text.
- Only temporal and quantity contradictions; no location, identity or narrative checks.
- Dates are not used to align times across sources (time-of-day comparisons may concern
  different days; the explanation says so).
- Reviewer identity is self-declared (no authentication).
- Graph layout is O(n²) per step; the API caps claim nodes (default 250).
- PDF preview requires PyMuPDF (already used for extraction).
- Claims are linked only through exact shared entities; generic nouns ("the truck") are
  not linked across documents, so differing times about an unnamed object are not
  compared (Missing Shipment: 0 potential inconsistencies under the rules).
- The temporal "why" text says "the same identifier" even when the shared entity is a
  location or contact.

## Commands
Backend tests: `cd backend; .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q`
Lint: `.\.venv\Scripts\python.exe -m ruff check --no-cache app tests`
Frontend: `npm.cmd run typecheck`, `npm.cmd run lint`,
`node --experimental-strip-types --no-warnings --test tests/audio-transcript.test.mjs tests/analysis-helpers.test.mjs tests/review-fixes.test.mjs`
Apply migration (after backup, with approval): `cd backend; .\.venv\Scripts\python.exe -m alembic upgrade head`
