# Phase 1 — Completion Report (frozen 2026-11-22)

Phase 1 is complete and browser-verified. This file preserves the completion evidence.

## Verification results (actual runner output)
| Check | Result |
|---|---|
| Backend pytest | 720 passed |
| Ruff check / format | All checks passed / files formatted |
| Frontend typecheck / lint | exit 0 / no warnings or errors |
| Frontend Node tests | 53/53 |
| Browser acceptance (headless Edge, CDP) | 47/47 checks passed |
| Production build | succeeded in an isolated copy; active `.next` untouched |

## Data state at freeze
- Database: `backend/var/evidencex.db`, Alembic `0006_analysis_not_null_ts`.
- Freeze backup: `backups/db/evidencex-20261122-220140-phase1-freeze.db`
  (sha256 `8df5c93e…0e0e`, integrity ok, 0 FK violations).
- Counts: cases 5, evidence 60, extractions 66, segments 909, claims 93, entities 179,
  relationships 12, contradictions 1, alternatives 2, analysis_runs 2, review_actions 4.
- Storage: 54 content-addressed files.

## Analysed cases
- **Missing Shipment Investigation** (real sample data): 88 claims (all grounded), 176
  entities, 430 mentions, 10 relationships, 0 potential inconsistencies, 0 candidates.
  Zero is correct under Phase 1 rules: the conflicting arrival accounts share no exact
  identifier (see Phase 2).
- **EvidenceX Synthetic Demo — Contradiction Review** (fictional, labelled): 5 claims,
  1 temporal potential inconsistency (SYN-40217, 09:15 vs 11:40, high severity,
  detection confidence 0.70, 2 machine-hypothesis alternatives), confirmed by a
  reviewer; audit trail recorded.

## Fixes made during completion
- `HH:MM:SS` parsing ("12:15:00" was read as "15:00").
- Compound record ids kept whole ("EX-004-EVE-001").
- Resolution candidates restricted (simple keys; misreading only for OCR/ASR sources;
  short numbers across different prefixes ignored).
- Duplicate-link IntegrityError fixed (pairs tracked within a pass).
- Vehicle/location patterns no longer match ordinary words or times.
- Entities/Graph empty states distinguish never/running/failed/completed-zero/filtered.
- Dashboard `main` is `min-w-0` (no horizontal overflow at 700 px).

## Known limitations carried into Phase 2
- Rule-based extraction only in the live data (no `GEMINI_API_KEY` configured).
- Only time and quantity comparisons; links require an exact shared entity.
- Dates are not normalized or used to align times; same-document accounts from
  different attributed sources are never compared.
- No timeline, no events, no report generation, no authentication; reviewer identity
  is self-declared.
- Git repository has no commits yet (all files untracked at freeze).
