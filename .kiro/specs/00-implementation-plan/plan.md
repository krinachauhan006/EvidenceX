# EvidenceX — Implementation Plan

Dependency-ordered plan across all specifications. Each stage is independently
demonstrable. Do not implement all specs at once; complete and verify a stage
before starting the next.

## Legend
- **Status**: planned | in-progress | done
- **Blocks**: specs that cannot start until this one is usable.

## Testing policy (applies to EVERY stage)
Tests are NOT deferred. Each stage ships unit + integration tests in the same
change, and the stage is not "done" until its tests pass. AI responses are always
mocked in tests. Never fabricate test results or accuracy metrics. Priority
coverage: upload/validation security, extraction+segment provenance,
claim-to-source links, temporal precision, contradiction detection, case-level
data isolation, AI structured-output validation, human review + audit history.

---

## Stage 0 — Foundation (prerequisite for everything)
Not a feature spec; the engineering baseline.

Scope:
- Backend: FastAPI app factory, `core/config.py`, `core/database.py`,
  `core/exceptions.py`, `core/logging.py`, health endpoint.
- First Alembic migration (empty baseline + `cases` table from Stage 1).
- `storage/local_store.py` interface + local implementation.
- `docker-compose.yml` (Postgres), `.env.example`, `pyproject.toml`.
- Frontend: Next.js App Router shell, Tailwind, shadcn/ui init, typed API client stub.

Acceptance criteria:
- `GET /health` returns 200 with service + DB connectivity status.
- Alembic `upgrade head` runs cleanly against a fresh Postgres.
- Frontend builds and renders an empty dashboard shell.

Blocks: ALL.

---

## Stage 1 — Case Management  (FIRST SPEC — authored)
Scope: create / list / view / update / archive / **delete** cases. A complete
full-stack vertical slice proving the chain works end to end. Ships with unit +
integration tests, including case-level data isolation.

Depends on: Stage 0.
Blocks: evidence-ingestion (evidence belongs to a case).

Acceptance criteria: see `specs/case-management/requirements.md`.
Tests: case CRUD happy paths + 404/422, archive filtering, and data isolation.

---

## Stage 2 — Evidence Ingestion
Scope: upload endpoint, magic-byte validation, size/type limits, content-addressed
local storage, `evidence` records with `processing_status`.

Depends on: Stage 1.
Blocks: document-processing.

Acceptance criteria:
- A valid PDF/image/audio uploads, is stored content-addressed, and yields an
  `evidence` record with status `pending`.
- Invalid or oversized files are rejected before storage with a clear error.
- File type is validated by magic bytes; path traversal via filename is impossible.
- Duplicate content within a case is detected via content hash.
Tests: magic-byte validation, size limits, path-traversal rejection, dedup.

---

## Stage 3 — Evidence Processing (PDF / Image OCR / Audio / CSV / XLSX / EML)
Full spec: `.kiro/specs/evidence-processing/` (requirements, design, tasks, testing).
Scope: PDF text (PyMuPDF), image OCR (Tesseract), audio transcription
(faster-whisper), CSV, XLSX (openpyxl) and EML (stdlib). Produces `extractions` +
`extraction_segments` with typed physical locators. Runs as FastAPI background tasks
with status transitions. Phased delivery P0-P8 (CSV vertical slice first).

Depends on: Stage 2.
Blocks: claim-extraction.

One module `processing/` with one extractor per format; engines behind interfaces.

Acceptance criteria:
- Each modality produces segments with correct locators (page+bbox or timestamps).
- Status transitions pending -> processing -> completed/failed are persisted.
- A failure on one evidence file is isolated and does not affect others.
- Failures are captured in `processing_error`; processing is retryable.
Tests: per-modality segment provenance, failure isolation, retry, status machine.

---

## Stage 4 — Structured Claim Extraction
Scope: Gemini client wrapper, versioned prompts, Pydantic output schemas. Each
claim is anchored to exactly one `extraction_segment`. One repair retry on
validation failure, then fail the artifact.

Depends on: Stage 3.
Blocks: entity-event-normalization, contradiction-engine.

Acceptance criteria:
- Every persisted claim references a valid segment (hard invariant enforced).
- AI output that fails schema validation is never persisted.
- `extraction_confidence` stored separately; never merged with other scores.
- Evidence text is passed as delimited untrusted data; injection text is analyzed
  as content, never followed as instructions.
Tests: schema-validation pass/fail/repair with MOCKED AI, claim-to-segment anchor
enforcement, injection-as-content handling.

---

## Stage 5 — Entity & Event Normalization
Scope: resolve claim text to canonical `entities`; build `events` with temporal
values preserving precision/uncertainty; link participants.

Depends on: Stage 4.
Blocks: contradiction-engine (needs normalized entities/events).

Acceptance criteria:
- Entity mentions link to canonical entities with `resolution_confidence`.
- Temporal values retain precision (exact|day|month|year|range|unknown).
- Approximate dates/times remain approximate; never auto-converted to exact values.
Tests: temporal normalization preserves precision; no false precision introduced.

---

## Stage 6 — Cross-Modal Contradiction Engine
Scope: detect contradictions across claims/modalities. Temporal contradictions
implemented first; the engine is a framework of pluggable detectors so numeric,
factual, entity-identity, and location detectors can be added without reshaping it.

Depends on: Stage 5.
Blocks: investigation-workspace (surfaces contradictions), report-generation.

Every contradiction record MUST contain: both claim ids, exact source references,
an explanation of the potential inconsistency, `detection_confidence` (separate
from truth), one or more alternative explanations, and a review status
(open|dismissed|confirmed).

Acceptance criteria:
- Temporal contradictions detected across evidence of different modalities.
- Each contradiction references two valid claims and includes all required fields
  above.
- Output language surfaces POTENTIAL inconsistencies only; no claim of
  guilt/deception/authentication.
Tests: temporal detector positive/negative cases, required-field completeness,
alternative-explanation presence, approximate-value preservation.

---

## Stage 7 — Investigation Workspace
Scope: four-panel workspace (left: evidence library + status; center: evidence
viewer; right: claims & findings; bottom: chronological timeline). Dark
navy/charcoal theme with amber = potential inconsistency, neutral = unresolved,
green = completed processing. Component structure and interactions are documented
in `specs/investigation-workspace/design.md` before complex screens are built.

Depends on: Stages 1-6 (reads their data).
Blocks: nothing (demo payoff).

Acceptance criteria:
- Clicking any claim navigates to its exact source location (PDF page, image
  region, or audio timestamp where supported).
- Contradictions are navigable from both involved claims.
- Color semantics applied consistently per the theme.

---

## Stage 8 — Human Review
Scope: accept / reject / edit claims and contradictions; every action recorded in
`review_actions`. Edited claims preserve original extracted text + anchor.

Depends on: Stage 4 (claims) and Stage 6 (contradictions); UI in Stage 7.

Acceptance criteria:
- Each review action is persisted with reviewer, target, and note.
- Editing a claim preserves the original text and provenance anchor for audit.
Tests: audit-history completeness, original-text preservation on edit, status
transitions for claims and contradictions.

---

## Stage 9 — Report Generation
Scope: generate a report from accepted claims, confirmed contradictions, and their
sources. Export format (PDF/HTML). Snapshot stored for reproducibility.

Depends on: Stages 4, 6, 8.

Acceptance criteria:
- Report includes only valid claims and confirmed contradictions.
- Every statement in the report cites its source evidence.
- Report language respects the "never adjudicate" safety invariants.

---

## Critical path
0 -> 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> (7, 8) -> 9

## Recommended first implementation
Stage 0 (Foundation) then Stage 1 (Case Management), WITH unit + integration tests
and lint checks run and reported. These prove the full stack and unblock all
downstream work. Everything after is incremental.
