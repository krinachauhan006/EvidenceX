# Phase 2 — Investigation Intelligence — Tasks

Execute stage by stage. Each stage ships with unit + integration tests and ends with
the full backend suite, frontend checks and (where UI changes) a browser check. Report
ACTUAL results. Stop at any blocking error or approval boundary. AI is always mocked.

Estimates are working days for one developer with Kiro. Total essential path ≈ 8 days;
with differentiating items ≈ 11; with optional items ≈ 13.

- [ ] 0. Freeze and baseline (0.5 d) — APPROVAL REQUIRED for the commit
  - Verify freeze backup `backups/db/evidencex-20261122-220140-phase1-freeze.db`.
  - With approval: initial Git commit of the Phase 1 tree (no db/storage/.env), tag
    `phase1-complete`. Work on branch `phase2`.
  - _Requirements: 12.2_

- [ ] 1. Temporal normalization v2 (1 d, no migration)
  - [ ] 1.1 `analysis/temporal.py`: normalize dates (ISO, text, slash with both
    readings), tz, inheritance from segment / email Date header / table row only.
  - [ ] 1.2 Wire into `extract.py` claim drafts (event_time JSON only).
  - [ ] 1.3 Date gate in `engine._temporal` (`different_day` → no record).
  - [ ] 1.4 Unit tests: precision never increases; no cross-evidence inheritance;
    ambiguous dates kept ambiguous; Phase 1 tests unchanged.
  - _Requirements: 1.1–1.6_

- [ ] 2. Migration 0007 (0.5 d) — APPROVAL + BACKUP REQUIRED before applying
  - [ ] 2.1 Models: `Event`, `EventClaim`, `Report`; columns on cases/claims/
    contradictions/review_actions (additive, nullable or defaulted).
  - [ ] 2.2 Migration up/down + `test_migration_schema` extension on a copy.
  - [ ] 2.3 Apply to the active DB only after approval; verify counts unchanged.
  - _Requirements: 12.4_

- [ ] 3. Event reconstruction + event-gated detection (2 d)
  - [ ] 3.1 `analysis/events.py`: accounts/attribution, object classes, proposal rule,
    reasons, missing links, `resolution_confidence`.
  - [ ] 3.2 Runner step: propose events after claims (idempotent; never re-propose a
    rejected grouping).
  - [ ] 3.3 Service/router: list/detail/review (`confirm|reject|note|add_claim|
    remove_claim`), transitions + 409, audit rows.
  - [ ] 3.4 `engine.detect_in_event` on confirm; `via_event_id`; context penalty;
    "different occurrences" alternative; rejected-event labelling.
  - [ ] 3.5 Tests: Missing Shipment sentences produce a proposed "truck arrival" event;
    planned ≠ actual; confirm → potential inconsistency 10:30 vs 12:15; proposed/
    rejected → none; isolation.
  - _Requirements: 2.1–2.6, 3.1–3.6_

- [ ] 4. Timeline + Events UI (2 d)
  - [ ] 4.1 `GET /timeline` (service-computed, no table).
  - [ ] 4.2 Timeline page: day lanes, points/ranges/unplaced, event grouping, amber
    conflicts, source navigation, filters, empty states (Phase 1 conventions).
  - [ ] 4.3 Events page + event card: accounts, reasons, missing links, confidence
    labels, confirm/reject/edit membership, history.
  - [ ] 4.4 Graph: event nodes and "account of" edges (additive).
  - [ ] 4.5 Node tests + browser checks (desktop + 700 px).
  - _Requirements: 4.1–4.5, 2.4–2.5_

- [ ] 5. Investigation report — deterministic (1.5 d)
  - [ ] 5.1 `analysis/reports.py` snapshot model + HTML renderer + language guard.
  - [ ] 5.2 API create/list/get/download (attachment, nosniff, CSP).
  - [ ] 5.3 Reports page (generate, list, open, download).
  - [ ] 5.4 Tests: only reviewed items; every statement cited; guard blocks banned
    wording; snapshot hash stable; isolation.
  - _Requirements: 5.1–5.5_

- [ ] 6. AI activation — hybrid, consent, tracking (2 d) [differentiating]
  - [ ] 6.1 Settings: `CLAIM_EXTRACTOR=hybrid`, default model update, `/api/ai/status`.
  - [ ] 6.2 Case consent toggle (API + UI), audited.
  - [ ] 6.3 Hybrid runner with per-item fallback; run stats; supersession rules.
  - [ ] 6.4 `claims_v2` prompt; response schema in requests; method badges in UI.
  - [ ] 6.5 Tests (fake transport): consent off ⇒ no call; fallback paths; supersession
    keeps reviewed claims; no key/evidence in logs.
  - _Requirements: 6.1–6.7_

- [ ] 7. AI event proposals + AI case brief (1.5 d) [differentiating]
  - [ ] 7.1 `events_llm.py` + `events_v1.txt`: group claim ids, validate ids/case.
  - [ ] 7.2 `brief_llm.py` + `brief_v1.txt`: citation validator, guard, labelling.
  - [ ] 7.3 Tests with fake transport incl. injection-as-content and invented ids.
  - _Requirements: 7.1–7.2, 8.1–8.3_

- [ ] 8. Optional (≈2 d total; only after stages 1–5 pass the browser gate)
  - [ ] 8.1 Audit hash chain + verify endpoint + UI badge. _Req 9_
  - [ ] 8.2 Case search over segments and claims. _Req 10_
  - [ ] 8.3 Location conflicts inside confirmed events. _Req 11_

- [ ] 9. Demo readiness and final verification (1 d)
  - Re-run analysis on Missing Shipment (after backup) to produce event proposals;
    walk the demo storyline; extend browser acceptance; full suites; isolated build;
    data-integrity check vs backup; update specs and completion report.
  - _Requirements: 12.1–12.3_
