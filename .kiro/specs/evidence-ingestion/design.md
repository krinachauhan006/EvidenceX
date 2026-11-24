# Evidence Ingestion — Design

## Overview
Adds an `evidence` feature module following the Stage 1 layering
(`router -> service -> repository`, distinct `models.py`/`schemas.py`). Extends the
existing `LocalStorage` (non-breaking) with streaming write, delete, and read.
Ships Alembic migration `0002_create_evidence` and unit + integration tests.

## Backend components

### Module `app/modules/evidence/`
- `models.py` — `Evidence` ORM model.
- `schemas.py` — `EvidenceOut`, `EvidenceList`, `EvidenceType` literal.
- `repository.py` — `EvidenceRepository`: `create`, `get_scoped`, `list_for_case`,
  `delete`, `count_by_hash`.
- `service.py` — `EvidenceService`: validation, storage orchestration, isolation,
  failure handling.
- `validation.py` — pure functions: extension/MIME/signature checks and
  modality resolution. Unit-tested in isolation.
- `router.py` — endpoints under `/api/cases/{case_id}/evidence`.

### Data model — `evidence` table
| column            | type         | notes                                        |
|-------------------|--------------|----------------------------------------------|
| id                | GUID (pk)    | uuid4                                         |
| case_id           | GUID (fk)    | -> cases.id, ON DELETE CASCADE, indexed       |
| original_filename | String(255)  | metadata only; never used to build a path     |
| stored_key        | String(64)   | the sha256 hex (storage key)                  |
| evidence_type     | String(16)   | document \| image \| audio                    |
| mime_type         | String(128)  | resolved/validated content type               |
| byte_size         | BigInteger   | > 0                                          |
| sha256            | String(64)   | lowercase hex digest of content               |
| storage_path      | String(512)  | relative path under storage root (not exposed)|
| processing_status | String(16)   | default "pending"                            |
| processing_error  | Text (null)  | populated by Stage 3+; unused now             |
| uploaded_at       | timestamptz  | from TimestampMixin.created_at                |

Index: `ix_evidence_case_uploaded (case_id, uploaded_at)` to back the list query.
`created_at` from `TimestampMixin` serves as `uploaded_at` (exposed under that name).
`updated_at` also comes from the mixin (consistency with cases).

### Storage extension (`app/storage/local_store.py`)
Add to `LocalStorage` without changing existing method signatures:
- `put_stream(fileobj) -> (sha256_hex, byte_size)` — reads in chunks, hashes while
  writing to a temp file, then atomically moves to the hash path. Avoids loading the
  whole file in memory and guarantees the final file matches its hash.
- `delete(content_hash) -> bool` — removes the blob for a hash (traversal-safe).
- `open(content_hash) -> BinaryIO` — opens the blob for streaming download.
Extend the `Storage` Protocol accordingly. Existing `put`/`path_for`/`exists`
remain intact so Stage 0/1 behavior and tests are unaffected.

### Validation (`validation.py`)
A registry maps extension -> (evidence_type, allowed mime types, signature
matcher). Steps:
1. Normalize and check the extension against the supported set (else 400).
2. Sniff a content prefix for a magic-byte signature:
   - PDF: `%PDF-`
   - PNG: `\x89PNG\r\n\x1a\n`
   - JPEG: `\xff\xd8\xff`
   - WEBP: `RIFF....WEBP`
   - WAV: `RIFF....WAVE`
   - MP3: `ID3` or MPEG frame sync `\xff\xe?`/`\xff\xf?`
   - M4A: ftyp box with `ftyp` at offset 4 and an audio brand (`M4A `, `mp42`,
     `isom`, etc.)
3. If a signature is recognized it MUST be consistent with the extension's modality;
   otherwise reject (400). For container formats where a strict signature is
   impractical (m4a brands vary), accept a recognized ftyp box.
The resolved `mime_type` comes from the server-side mapping, not the client.

### Service flow (upload)
1. `case = cases.get(case_id)` — 404 if missing (reuse `NotFoundError`).
2. Read the upload in chunks: enforce the size cap WHILE reading (fail fast at
   `MAX_UPLOAD_SIZE_MB`), and capture the first bytes for signature sniffing.
   Reject empty (400) and oversized (400) before persisting.
3. Validate extension + signature -> `evidence_type`, `mime_type` (400 on failure).
4. `sha256, size = storage.put_stream(...)` — blob written first (idempotent for
   duplicates).
5. Create the `evidence` record; `commit`. If the DB commit fails, delete the blob
   iff no other record references the hash (no orphans).
6. Return `EvidenceOut`.

### Service flow (get/download/delete — all scoped)
- `get_scoped(case_id, evidence_id)` returns the row only if BOTH match; otherwise
  the service raises `NotFoundError`. This is the single isolation choke point.
- Download: look up scoped, open the blob (`storage.open`), stream with
  `Content-Disposition: attachment; filename="<original>"` and the stored mime type.
  Missing blob -> 404.
- Delete: look up scoped, delete the record, then delete the blob iff
  `count_by_hash(hash) == 0` after removal. Blob removal failure is logged, not
  fatal (record is already gone; a dangling blob is harmless and GC-able).

### Exceptions
Add `BadRequestError` (400) to `app/core/exceptions.py` for validation failures
(empty/oversized/unsupported/signature). `NotFoundError` (404) covers missing case,
missing evidence, and cross-case access. Pydantic/FastAPI still yields 422 for
malformed UUIDs in the path.

### Router endpoints (all under the owning case)
```
POST   /api/cases/{case_id}/evidence              multipart/form-data: file -> 201 EvidenceOut
GET    /api/cases/{case_id}/evidence              -> 200 EvidenceList
GET    /api/cases/{case_id}/evidence/{id}         -> 200 EvidenceOut | 404
GET    /api/cases/{case_id}/evidence/{id}/download -> 200 stream | 404
DELETE /api/cases/{case_id}/evidence/{id}         -> 204 | 404
```
Mounted in `app/main.py` alongside the cases router.

### Case delete integration
`CaseService.delete` currently relies on FK cascade for rows. To also clean blobs
(Requirement 6.3), the evidence service exposes `cleanup_case_blobs(case_id)` which
the case delete calls BEFORE removing the case (collect hashes, delete case via
cascade, then remove now-unreferenced blobs). Best-effort; wrapped so a blob error
cannot break the case delete. This is the only touch to Stage 1 code and it is
additive.

## Configuration
Add `max_upload_size_mb: int = 25` (env `MAX_UPLOAD_SIZE_MB`) to `Settings`. Add to
`.env.example`.

## Migration — `0002_create_evidence`
`down_revision = "0001_create_cases"`. Creates the `evidence` table with the
`case_id` FK (`ondelete="CASCADE"`) and the composite index. Uses the shared `GUID`
type for portability. `downgrade` drops the index then the table.

Note: SQLite does not enforce FK cascade unless `PRAGMA foreign_keys=ON`. Tests
create schema via `Base.metadata.create_all`; the service-level cleanup and scoped
queries do not rely on DB cascade for correctness of isolation, and case-delete
cascade is covered by the FK on Postgres. A SQLite `PRAGMA foreign_keys=ON` event
listener is added in `database.py` so cascade also works under SQLite.

## Frontend
- `lib/types/evidence.ts` — `Evidence`, `EvidenceList`, `EvidenceType` mirroring
  schemas.
- `lib/api/evidence.ts` — `listEvidence`, `getEvidence`, `uploadEvidence` (FormData),
  `deleteEvidence`, `evidenceDownloadUrl`. Upload uses `XMLHttpRequest` to report
  progress; others use the existing `apiFetch` where JSON, or a direct fetch for
  multipart. A dedicated `apiUpload` helper is added to `lib/api/client.ts` that
  does NOT force a JSON content-type.
- `components/evidence/evidence-section.tsx` — the case-detail Evidence panel:
  drag-and-drop + browse, multi-file, type/size guidance, per-file progress,
  success/failure, list with icon/filename/type/size/date, download, delete w/
  confirm, empty state. Dark navy/charcoal theme; green = processed/pending-done,
  amber reserved for inconsistencies (not used here), neutral for unresolved.
- `components/evidence/file-type-icon.tsx` — Lucide icon per modality.
- Mounted inside `app/(dashboard)/cases/[caseId]/page.tsx` as a new section below
  the case actions. No existing behavior removed.

## Testing
- `tests/unit/test_evidence_validation.py` — signature/extension/modality matrix,
  SHA-256 correctness, size/empty logic (pure functions + storage).
- `tests/integration/test_evidence_api.py` — full endpoint matrix incl. isolation,
  invalid case id, missing blob handling, duplicate upload, delete + blob cleanup.
- `conftest.py` — register the evidence model import so its table is created; add a
  `tmp` storage root override so tests write blobs to a temp dir, and a small set of
  valid tiny fixture files (generated in-code) per modality.
- Existing cases tests remain untouched.
