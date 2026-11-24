# Phase 2 — Investigation Intelligence — Design

Status: PLANNED (not implemented). Requires approval before any code or migration.

## 1. Current architecture (inspected 2026-11-22)
Modular monolith: FastAPI backend (one process, SQLite in WAL mode, Alembic at
`0006_analysis_not_null_ts`) and a Next.js 14 App Router frontend. REST only.

| Area | Implemented | Limitation relevant to Phase 2 |
|---|---|---|
| Ingestion | magic-byte validation, SHA-256 content addressing, atomic writes, dedupe | — |
| Processing | PDF, OCR, ASR (faster-whisper `base`), CSV, XLSX, EML; typed locators; retryable | OCR/ASR uncertainty only as notes |
| Claims | `rule_based_v1` sentence rules; verbatim quote + offsets; grounding check | rules only in live data |
| AI | `app/ai/gemini_client.py` (stdlib HTTP, Pydantic validation, one repair), `claims_llm.py`, `prompts/claims_v1.txt`; mocked tests | off by default; default model `gemini-2.0-flash` is now legacy-only; JSON mode without a response schema; no fallback; no per-case consent; switching method creates a parallel claim set |
| Entities | exact `normalized_key`; candidates never merged | no context linking; no `resolution_confidence` |
| Contradictions | `engine.detect`: same entity + same `predicate_key`, different evidence; temporal (>10 min) and quantity | dates ignored; same-document accounts never compared; identifier required |
| Review | claims, relationships, entities, contradictions, segment corrections; append-only `review_actions` | reviewer self-declared; audit not tamper-evident |
| UI | case shell, evidence workspace with 6 viewers, claims, entities, contradictions, SVG graph, review queue | no timeline, no events, no report |

## 2. Proposed architecture changes
All new logic stays inside `app/modules/analysis/` (no new service, no new process).

```
analysis/
  temporal.py      NEW  pure: date normalization, inheritance, comparability
  events.py        NEW  pure: event proposal rules, accounts/attribution, reasons
  engine.py        EXT  detect() gains event-scoped comparison + date gate
  runner.py        EXT  hybrid extractor selection, fallback, supersession, event step
  reports.py       NEW  pure: report model + HTML rendering + language guard
  audit.py         NEW  pure: canonical hash + chain verification (optional R9)
  repository/service/router/schemas  EXT
app/ai/
  gemini_client.py EXT  optional response JSON schema, model probe (no evidence sent)
  claims_llm.py    EXT  prompt claims_v2 (event type, attribution)
  events_llm.py    NEW  event grouping proposals over claim ids
  brief_llm.py     NEW  cited case brief
  prompts/claims_v2.txt, events_v1.txt, brief_v1.txt  NEW (versioned)
frontend/
  app/(dashboard)/cases/[caseId]/timeline/page.tsx  NEW
  app/(dashboard)/cases/[caseId]/events/page.tsx    NEW
  app/(dashboard)/cases/[caseId]/reports/page.tsx   NEW
  components/analysis/timeline.tsx, event-card.tsx, method-badge.tsx  NEW
  case settings: "Allow external AI processing" toggle (explicit, audited)
```

### 2.1 Temporal v2 (`temporal.py`, pure)
`normalize(claim, segment_context) -> TemporalValue` with fields: `raw`, `kind`,
`precision` (`exact|range|unknown`), `minutes|range`, `date` (ISO or null),
`date_raw`, `date_precision` (`day|inherited_day|ambiguous|unknown`), `date_source`
(`sentence|segment|email_header|table_row`), `date_alternatives` (ambiguous slash
dates), `tz`, `tz_known`. Stored inside the existing `claims.event_time` JSON (no
column change). `comparable(a, b)` returns `same_day | different_day | unknown_day`.
The temporal rule skips `different_day`.

### 2.2 Events (`events.py`, pure)
- **Account:** `(evidence_id, attribution)` where attribution is a detected source
  phrase at the start of the sentence/bullet (`Delivery receipt:`, `Witness statement
  says`, `Gate log:`), else null.
- **Object class:** small closed vocabulary (truck, vehicle, van, shipment,
  consignment, delivery, parcel) mapped to a class; never free-text NER.
- **Proposal rule:** group claims by `(event_type, object_class or exact entity)`, then
  split by date compatibility. Keep groups with ≥2 accounts. `resolution_confidence`
  is a transparent score: identifier 0.8, plate/location 0.6, object class only 0.35;
  −0.1 when a date is inherited or missing on one side; clamped 0.1–0.9.
- **Reasons:** each member gets `match_reasons` (e.g. `same event type: arrival`,
  `same object: truck`, `same date: 2026-10-12`), the event gets `missing_links`.
- Planned vs actual are separate event types (`planned_arrival` ≠ `arrival`).

### 2.3 Event-gated detection (`engine.py`)
`detect_in_event(event, members)` runs only for `confirmed` events. Pairs are
different accounts (different evidence, or same evidence with two distinct
attributions). Reuses `_temporal` / `_quantity` with: date gate, confidence penalty
for `link_basis != identifier` (−0.15) and an uncertainty note listing
`missing_links`. Adds alternative "the grouped accounts may describe different
occurrences". Existing identifier-based detection is unchanged.

### 2.4 AI activation
- Modes: `rule_based` (default) | `gemini` | `hybrid`. Effective only with key AND case
  consent; otherwise rule-based, and the run stats say why.
- Hybrid: per evidence item try AI, on `AIError` fall back to rules; stats record
  `ai_items`, `fallback_items`, `fallback_reasons` (error types only).
- Supersession: new nullable `claims.superseded_by_run_id`. When a run produces claims
  for an extraction with a different method, older **unreviewed** claims of that
  extraction get the new run id; reviewed claims stay active and are flagged
  "kept: reviewed under an earlier method". Lists default to active claims.
- Model: default `GEMINI_MODEL=gemini-3.8-flash` (listed Stable on the Gemini models
  page, Nov 2026), configurable; `GET /api/ai/status` probes model metadata without
  sending evidence. Final model choice is verified with a real key before the demo.
- Structured output: send the Pydantic JSON schema as the response schema where the
  API accepts it; local Pydantic validation stays authoritative.

### 2.5 Reports (`reports.py`)
Deterministic snapshot builder → typed `ReportModel` → HTML (escaped, no scripts,
served as attachment with `nosniff` and a restrictive CSP). Sections: case summary
counts, confirmed events with accounts, potential inconsistencies with reviewer
decisions and alternatives, verified claims by evidence, method & confidence notes,
limitations, unreviewed appendix (counts only). Language guard: deny-list regex
(guilty, lied, lying, deceptive, proves, authentic, fraud committed, …) applied to
generated text; failing text is not emitted.

### 2.6 Audit chain (optional)
`hash = sha256(prev_hash || canonical_json(case_id, target_type, target_id, action,
from, to, note, payload, reviewer, created_at))`. Rows created before migration 0007
are covered by a per-case genesis digest computed at verification time (no rewrite
of existing rows).

## 3. Database changes — migration `0007_phase2_events` (additive only)
| Change | Detail |
|---|---|
| `cases.ai_processing_allowed` | BOOLEAN NOT NULL DEFAULT false |
| `claims.superseded_by_run_id` | nullable FK → analysis_runs (SET NULL); index |
| `events` (new) | id, case_id (cascade), event_type, title, temporal JSON, anchor_entity_id (nullable FK), object_class, link_basis, resolution_confidence FLOAT, match_summary JSON, missing_links JSON, origin, status (`proposed|confirmed|rejected`), review_note, reviewed_by, reviewed_at, created_at, updated_at; index (case_id, status) |
| `event_claims` (new) | id, case_id, event_id (cascade), claim_id (cascade), account_label, attribution, match_reasons JSON, added_by (`system|reviewer|ai`), created_at; unique (event_id, claim_id) |
| `contradictions.via_event_id` | nullable FK → events (SET NULL) |
| `reports` (new) | id, case_id (cascade), title, format, content (TEXT), content_sha256, snapshot JSON, brief_method nullable, created_by, created_at |
| `review_actions.prev_hash`, `.hash` | nullable VARCHAR(64) (optional R9) |
Existing rows are not rewritten. Downgrade drops only the new objects. Tested on a copy
like `test_migration_schema.py`, applied only after a verified backup and approval.

## 4. API changes (all under `/api/cases/{case_id}` unless noted)
| Method | Path | Purpose |
|---|---|---|
| PATCH | `/api/cases/{id}` | adds `ai_processing_allowed` (audited) |
| GET | `/api/ai/status` | configured?, mode, model, reachable (no evidence sent, no key) |
| POST | `/analysis` | optional body `{"extractor": "rule_based|gemini|hybrid"}`; 400 if AI not permitted |
| GET | `/events`, `/events/{id}` | list/detail with members, accounts, reasons |
| POST | `/events/{id}/review` | `confirm|reject|note|add_claim|remove_claim` (409 on invalid transitions) |
| POST | `/events/propose-ai` | optional AI grouping (R7) |
| GET | `/timeline` | ordered items + groups; filters evidence/modality/event/status |
| POST/GET | `/reports`, `/reports/{id}`, `/reports/{id}/download` | create snapshot, list, view, download |
| GET | `/reviews/verify` | audit chain status (optional) |
| GET | `/search?q=` | segments + claims, case-scoped (optional) |
Existing endpoints keep their contracts; list endpoints gain additive fields only
(`via_event_id`, `superseded`, `method`).

## 5. Updated data flow
```
Upload → validate → store → process (segments + locators)
  → claims  [rule_based | gemini | hybrid → fallback]   (method per claim; supersession)
  → temporal v2 normalization (dates, inheritance, tz)
  → entities (exact keys) + candidates (reviewer)
  → identifier-based detection (Phase 1, now date-gated)
  → EVENT PROPOSALS (rules; optional AI)  ──► reviewer confirms / rejects / edits
  → event-gated detection on confirmed events → potential inconsistencies
  → timeline · graph (event nodes) · review queue
  → reviewed items → REPORT snapshot (+ optional AI brief with enforced citations)
```

## 6. Testing strategy
- Unit (pure): temporal normalization (ISO/text/slash-ambiguous, inheritance sources,
  no cross-evidence inheritance, tz, different-day gate); events (positive grouping on
  Missing Shipment sentences, planned≠actual, different dates split, no anchor → no
  event, attribution parsing, confidence math); event-gated detection (no records for
  proposed/rejected; same-evidence only with two attributions); report language guard;
  brief citation validator; audit hash/verify incl. tamper detection.
- AI (fake transport only): consent off → zero transport calls; hybrid fallback on
  invalid output and on unavailable; unknown/cross-case ids dropped; supersession
  keeps reviewed claims; model probe sends no evidence; key never in logs/errors.
- Integration (API, in-memory DB): events lifecycle + 409s + audit rows; confirm →
  inconsistency appears with `via_event_id`; reject → kept and labelled; timeline
  ordering and "date not stated" bucket; report contains only reviewed items and
  citations; case isolation for every new endpoint; migration 0007 up/down on a copy.
- Frontend: Node tests for timeline layout helpers, event labels, method badges.
- Browser acceptance (extend `verify_final.py`): timeline renders and navigates to
  source; confirm event in UI → amber inconsistency appears; report download opens;
  AI-off labels; narrow viewport; no console errors.
- Regression gate: 720 backend + 53 frontend tests stay green at every stage.

## 7. Security and privacy
- External AI is opt-in per case (default off), audited, and requires server config.
- Only segment text + ids are sent, inside delimiters; injection text stays data
  (existing tests extended to events/brief prompts).
- Model outputs never drive control flow unvalidated; ids are checked against the
  case; quotes re-grounded; times re-read locally.
- Logs: counts, ids, error types; never evidence text, prompts, responses or keys.
- Reports: escaped HTML, attachment download, CSP, no remote resources.
- Reviewer identity remains self-declared (documented in UI and report); real
  authentication/authorization is deferred. Optional hash chain makes edits evident.
- Provider retention: the UI consent text states that text is sent to Google's API
  under the operator's account terms.

## 8. Demo storyline (target)
1. Missing Shipment → **Timeline**: four timed accounts of the truck on 12 Oct; system
   proposes "Truck arrival" event (context link, reasons + missing links shown).
2. Reviewer confirms the event → engine surfaces 10:30 (delivery receipt) vs 12:15
   (witness statement) as a potential inconsistency with alternatives (different
   trucks, planned vs actual, clock difference). Amber on timeline and graph.
3. Open each account at its exact source (PDF bbox, audio timestamp).
4. Toggle AI on (if a key is available) → hybrid run, method badges, fallback count.
5. Generate the **report**: every statement cited; optional AI brief with citations.
6. Synthetic case still demonstrates the identifier-based path; audit chain "intact".

## 9. Risks and fallbacks
| Risk | Mitigation / fallback |
|---|---|
| No Gemini key at demo time | Essential features are rule-based; AI parts degrade to labelled "not configured" |
| Model name churn / rate limits | configurable model, status probe, hybrid fallback |
| Context linking false positives | proposals only; reasons + missing links; reviewer gate; lower confidence |
| Migration breaks Phase 1 | single additive migration, tested on a copy, backup first, downgrade path |
| Scope creep | optional items R9–R11 only after essentials pass the browser gate |
| Uncommitted repository | baseline commit (with approval) before Phase 2 work |
| Slow local tooling (observed) | run suites once per stage; browser checks scripted |
