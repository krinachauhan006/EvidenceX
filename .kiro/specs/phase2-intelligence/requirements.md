# Phase 2 — Investigation Intelligence — Requirements

## Introduction
Phase 1 delivered provenance-first ingestion, rule-based claims, exact-identifier
entities, temporal/quantity potential inconsistencies, human review, audit history and
a knowledge graph. Its main analytical gap is visible on the flagship case: the
"Missing Shipment Investigation" is about conflicting arrival times, yet Phase 1 finds
0 potential inconsistencies, because the accounts ("Delivery receipt: Truck arrived
10:30", "Witness statement: Truck arrived 12:15") share no identifier and dates are not
used.

Phase 2 makes EvidenceX reason about **events** rather than only identifiers, shows the
case as a **timeline of accounts**, activates **source-grounded AI** safely, and
produces a **cited investigation report**. Every new inference is proposed with its
reasons and gated by a human decision.

## Scope (prioritised)
- Essential: R1 temporal normalization v2, R2 event reconstruction, R3 event-gated
  conflict detection, R4 timeline, R5 investigation report (deterministic).
- Differentiating: R6 AI activation (hybrid extraction, consent, method tracking),
  R7 AI event proposals, R8 AI case brief with enforced citations.
- Optional: R9 tamper-evident audit chain, R10 cross-document search, R11 location
  conflicts inside confirmed events.
- Deferred (explicitly out of scope): authentication and multi-user authorization,
  free-text person/organisation entity resolution, video, task queue / Postgres
  cut-over, React Flow, automatic merging of any kind, deception or credibility scoring.

## Requirements

### Requirement 1 — Temporal normalization v2
**User story:** As an investigator, I want dates attached to times so that accounts of
different days are not compared as if they were the same day.

#### Acceptance criteria
1. WHEN a claim's sentence contains a date THEN the system SHALL store a normalized
   date (`YYYY-MM-DD`) with precision `day`, and keep `date_raw` exactly as written.
2. WHEN a date is ambiguous (e.g. `03/04/2026`) THEN the system SHALL keep both
   readings as uncertainty and SHALL NOT pick one.
3. WHEN a claim has a time but no date THEN the system MAY inherit a date only from
   (a) the same segment, (b) an email `Date` header of the same message, or (c) a
   table row's date column, and SHALL record `date_source` and lower the precision
   label to `inherited_day`. It SHALL NOT inherit across evidence items.
4. WHEN two times have known dates that differ THEN the temporal rule SHALL NOT report
   a time-of-day inconsistency between them.
5. WHEN a time zone is stated (email header offset) THEN it SHALL be stored; otherwise
   `tz_known=false` SHALL be stored and mentioned in explanations.
6. Vague times SHALL remain ranges; no value SHALL gain precision it did not have.

### Requirement 2 — Event reconstruction (proposed, never assumed)
**User story:** As an investigator, I want the system to propose which claims describe
the same real-world occurrence, with its reasons, so I can confirm or reject the link.

#### Acceptance criteria
1. The system SHALL propose an event when two or more claims share the same event type
   (`predicate_key`, e.g. `arrival`), a compatible date (equal, or unknown on at most
   one side), and a shared anchor: an exact entity (identifier, vehicle plate,
   location) OR the same object noun class (e.g. "truck") within the same case.
2. Each proposal SHALL store `link_basis` (`identifier` | `context` | `ai_proposed`),
   per-claim `match_reasons`, explicit `missing_links` (e.g. "no shared identifier",
   "date stated in only one source"), and a `resolution_confidence` that is a
   separate field, never merged with extraction or detection confidence.
3. Planned and actual events (`planned_arrival` vs `arrival`) SHALL never be merged
   into one event; they MAY be shown as related.
4. Proposed events SHALL have status `proposed`. Only a reviewer action SHALL set
   `confirmed` or `rejected`; every action SHALL be written to `review_actions`.
5. A reviewer SHALL be able to remove a claim from, or add an existing claim of the
   same case to, a proposed event. Claims and their source anchors SHALL never change.
6. Each event member SHALL record its **account**: the evidence item plus any detected
   attribution phrase ("Delivery receipt", "Witness statement"), so two accounts in one
   document are distinguishable.

### Requirement 3 — Event-gated conflict detection
**User story:** As an investigator, I want potential inconsistencies between accounts
of an event I have confirmed, including accounts quoted in the same document.

#### Acceptance criteria
1. WHEN an event is confirmed THEN the engine SHALL compare its members' times (and
   quantities) across different accounts and create potential inconsistencies with
   `via_event_id` set.
2. Accounts from the same evidence item SHALL be compared only when both carry
   distinct attribution phrases; the explanation SHALL say so.
3. Context-linked (`link_basis=context|ai_proposed`) comparisons SHALL carry a lower
   `detection_confidence` and an uncertainty note naming the missing links.
4. No potential inconsistency SHALL be created from an event that is `proposed` or
   `rejected`.
5. Every record SHALL contain all Phase 1 required fields (both claim ids, source
   references, explanation, detection_confidence, ≥1 alternative explanation, review
   status). Alternatives SHALL include "different occurrences grouped together".
6. Rejecting a previously confirmed event SHALL NOT delete its potential
   inconsistencies; they SHALL be shown as "event link rejected" and remain auditable.

### Requirement 4 — Case timeline
**User story:** As an investigator, I want a chronological view of every timed claim,
grouped by event, so I can see conflicting accounts at a glance.

#### Acceptance criteria
1. The timeline SHALL list claims with an `event_time`, ordered by normalized date and
   time; items without a date SHALL be grouped as "date not stated", never placed on a
   guessed day.
2. Exact times SHALL render as points, ranges as bars, unknown/ambiguous values as
   unplaced items with their raw text.
3. Members of an event SHALL be grouped; accounts in a potential inconsistency SHALL be
   amber; unreviewed proposals SHALL be neutral.
4. Every item SHALL navigate to its exact source location (existing source links).
5. Filters: evidence item, modality, event, review status.

### Requirement 5 — Investigation report (deterministic)
**User story:** As an investigator, I want an exportable report of what has been
reviewed, where every statement cites its source.

#### Acceptance criteria
1. A report SHALL include only verified claims, confirmed events and potential
   inconsistencies with reviewer decisions, plus a clearly separated "unreviewed"
   appendix count (no unreviewed content presented as findings).
2. Every statement SHALL cite evidence name + exact locator (page/bbox, timestamp,
   row/cell, header/part) and the claim id.
3. The report SHALL state the extraction method per claim and that confidence values
   are self-assessments, not truth.
4. Report text SHALL pass a language guard: no wording asserting guilt, lying,
   deception, authenticity or proof.
5. Each generated report SHALL be stored as an immutable snapshot (content hash, list
   of included ids and their statuses) and served as a non-executable download.

### Requirement 6 — AI activation (hybrid, consented, tracked)
**User story:** As an investigator, I want AI extraction when it is allowed and
configured, with rule-based fallback and clear labelling of which method produced what.

#### Acceptance criteria
1. AI SHALL be used only when (a) `CLAIM_EXTRACTOR` is `gemini` or `hybrid`,
   (b) `GEMINI_API_KEY` is set, and (c) the case has `ai_processing_allowed=true`.
   Otherwise no request SHALL be made.
2. In `hybrid` mode, an AI failure for an evidence item SHALL fall back to rule-based
   extraction for that item; the run stats SHALL record the fallback and reason type.
3. Every claim SHALL keep its `extraction_method`; the UI SHALL label AI-extracted
   claims and show `extraction_confidence` as a self-assessment.
4. When a newer method's claims exist for an extraction, older unreviewed claims SHALL
   be marked superseded (not deleted); reviewed claims SHALL never be superseded
   silently.
5. The model name SHALL be configurable and checked at startup without sending
   evidence; the default SHALL be a currently supported model.
6. Requests SHALL contain only segment text and ids inside data delimiters; no file
   bytes, filenames or secrets; logs SHALL record counts and error types only.
7. Structured output SHALL be requested from the API where supported, and Pydantic
   validation SHALL remain the authority (one repair, then fail/fallback).

### Requirement 7 — AI event proposals
1. WHEN AI is allowed THEN the system MAY ask the model to group existing claim ids into
   candidate events with a rationale; unknown or cross-case ids SHALL be dropped.
2. AI proposals SHALL be stored with `link_basis=ai_proposed`, the model's
   `resolution_confidence`, and status `proposed`. They SHALL never be auto-confirmed.

### Requirement 8 — AI case brief with enforced citations
1. The brief SHALL be generated only from reviewed items passed as data.
2. Every sentence SHALL cite ≥1 claim id from that input; uncited or unknown-id
   sentences SHALL be removed and counted; the brief SHALL pass the language guard.
3. The brief SHALL be labelled "AI-drafted summary — review before use" and stored
   with the report snapshot, method and model.

### Requirement 9 (optional) — Tamper-evident audit chain
1. Each new `review_actions` row SHALL store `prev_hash` and `hash` (SHA-256 over
   canonical fields) per case.
2. `GET /reviews/verify` SHALL report intact/broken and the first broken position.

### Requirement 10 (optional) — Cross-document search
1. Search SHALL cover segment text and claims within ONE case, return source locators,
   and open the exact source on click. Queries SHALL be parameterized.

### Requirement 11 (optional) — Location conflicts inside confirmed events
1. Within a confirmed event, different location entities for the same occurrence MAY
   be reported as a `location` potential inconsistency with alternatives.

### Requirement 12 — Safety, isolation and tests
1. All new tables SHALL be case-scoped with cascade delete; cross-case ids SHALL 404.
2. Phase 1 behaviour SHALL remain unchanged unless a requirement above changes it;
   all 720 backend and 53 frontend tests SHALL keep passing.
3. AI SHALL always be mocked in tests; results SHALL be reported as actually produced.
4. Schema changes SHALL ship as one reviewed Alembic migration, applied only after a
   verified backup and explicit approval.
