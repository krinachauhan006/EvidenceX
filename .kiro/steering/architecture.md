# EvidenceX — Architecture

## Shape
Modular monolith, two deployables:
- `backend/` — FastAPI (Python), one process.
- `frontend/` — Next.js App Router (TypeScript), one process.

No microservices. Modules talk through in-process service calls, not network hops.
Communication between frontend and backend is REST only.

## Backend module layout
Feature modules under `backend/app/modules/<feature>/`, each self-contained with:
- `router.py`    — HTTP endpoints (thin; delegates to service).
- `service.py`   — business logic and orchestration.
- `repository.py`— data access (SQLAlchemy queries).
- `models.py`    — SQLAlchemy ORM models.
- `schemas.py`   — Pydantic request/response models.

Cross-cutting concerns live in `backend/app/core/` (config, database, security,
logging, exceptions). AI lives in `backend/app/ai/`. File storage lives in
`backend/app/storage/`.

## Pipeline flow
```
Upload
  -> Evidence stored (content-addressed, validated)
  -> Processing (PDF text | image OCR | audio transcript)
       -> extractions + extraction_segments (provenance anchors)
  -> Claim extraction (Gemini, schema-validated, anchored to a segment)
  -> Entity/Event normalization (resolution + linking)
  -> Contradiction engine (cross-modal comparison; temporal first)
  -> Findings in workspace
  -> Human review
  -> Report
```

## Processing concurrency
- PDF text extraction: fast, synchronous.
- OCR and audio transcription: slow, CPU-bound -> background processing.
- MVP uses in-process background tasks (FastAPI BackgroundTasks) plus a persisted
  `processing_status` per evidence record. The UI polls status.
- Introduce a real task queue (Celery/Redis) ONLY if demo load requires it.
  Do not add it preemptively.

## Processing module structure & failure isolation
- Evidence processing is ONE specification (`.kiro/specs/evidence-processing/`),
  implemented as one module `app/modules/processing/` with one extractor per format
  under `processing/extractors/`:
  - `pdf.py` — PyMuPDF text blocks (page + bbox locators).
  - `image_ocr.py` — Tesseract OCR lines (pixel bbox locators).
  - `audio.py` — faster-whisper transcript segments (start/end locators).
  - `csv_extractor.py`, `xlsx.py` — tabular rows (row/column and sheet/cell locators).
  - `eml.py` — email headers, body parts, attachment metadata (part locators).
  - `processing/runner.py` — background orchestration, atomic claim, status tracking.
- Extractors are pure functions of bytes. They never touch the database, storage or
  HTTP. Heavy libraries are imported lazily so a missing engine only fails the
  affected item (`dependency_missing`), never the application.
- Background jobs use FastAPI `BackgroundTasks` with their OWN database session and
  claim each item atomically at execution time. Extraction runs behind an
  `ExtractionExecutor` seam (inline now, subprocess possible later).
- New evidence types: `tabular` (csv, xlsx) and `email` (eml).
- Engine selection (PyMuPDF / Tesseract / faster-whisper) is subject to environment
  compatibility; each engine sits behind a small interface so it can be swapped.
- Failure isolation: a processing failure on ONE evidence file MUST NOT affect
  others. Each file's failure is captured in `processing_error` with a clear state,
  and processing is retryable (status can return to `pending` to re-run).
- Every extracted segment preserves provenance: page numbers, bounding boxes, and
  audio timestamps are stored wherever the modality makes them available.

## AI boundary
- All Gemini access goes through a single client wrapper (`app/ai/gemini_client.py`).
- The wrapper returns a validated Pydantic model or raises — never free-form text
  to business logic.
- On schema-validation failure: retry once with a repair prompt, then fail the
  artifact. Never guess or fabricate to satisfy a schema.
- Prompts are versioned templates under `app/ai/prompts/`.

## Provenance model (hard invariant)
- `extraction_segments` carry the physical locator (typed JSON `locator`, with
  `page`, `t_start`, `t_end` also promoted to indexed columns):
  - PDF/image: `page` + `bbox` ([x0,y0,x1,y1]).
  - audio: `t_start` / `t_end` timestamps.
  - CSV: `row` + column names. XLSX: `sheet` + `row` + cell `range`/coordinates.
  - EML: header name or part (`body_text`, `body_html`, `attachment`).
- OCR/ASR engine confidence is stored as `engine_confidence` on segments. It is
  separate from claim-level `extraction_confidence` (Stage 4).
- Every claim references exactly one segment (its anchor).
- Every finding references the claim ids it rests on.
- No claim without a source anchor. No finding without valid claims.

## Confidence model
Confidence is tracked separately at each stage and never merged into a single score:
- `extraction_confidence` (claim extraction)
- `resolution_confidence` (entity resolution)
- `detection_confidence` (contradiction detection)
Extraction/detection confidence is the model's self-assessed certainty, NOT a
statement about factual truth.

## Temporal model
Temporal values are stored as JSONB with explicit precision and uncertainty
(`exact | day | month | year | range | unknown`). Never coerce vague time
references into false precision.

## Storage & security
- Uploads are untrusted: validate by magic bytes (not extension), cap size,
  store under content-addressed names outside any web-served path, never execute.
- Local filesystem storage for the MVP via `app/storage/local_store.py`, behind
  an interface so a future object store can be swapped in.

## Contradiction engine framework
- Temporal contradiction detection is implemented first.
- The engine is designed as a framework of pluggable detectors so future
  detector types (numeric, factual, entity-identity, location) drop in without
  reshaping the pipeline. Each detector consumes normalized claims/events and emits
  contradiction records.
- Every contradiction record carries: both claim ids, exact source references,
  an explanation, `detection_confidence` (separate from truth), one or more
  alternative explanations, and a review status. See `safety-and-provenance.md`.

## Frontend workspace layout (built incrementally)
- Dark navy/charcoal theme. Amber = potential inconsistency; neutral = unresolved
  finding; green = completed processing.
- Four-panel investigation workspace (target state):
  left = evidence library + status, center = evidence viewer, right = claims &
  findings, bottom = chronological timeline.
- Claim -> source navigation jumps to PDF page, image region, or audio timestamp.
- Document component structure and interactions before implementing complex screens.

## Data contract
- Backend Pydantic schemas are the source of truth.
- Frontend TS types mirror them; prefer generating from the FastAPI OpenAPI schema
  to prevent drift.

## Database
PostgreSQL, SQLAlchemy ORM, Alembic migrations. UUID primary keys. Status columns
drive both the review workflow and the polling UI. See `coding-standards.md` for
conventions and `safety-and-provenance.md` for invariants that must never break.
