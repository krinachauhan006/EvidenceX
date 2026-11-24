# Evidence Ingestion — Tasks

Execute top to bottom in small, verifiable steps. Tests ship WITH the code. Run
pytest + ruff (backend) and typecheck/lint/build (frontend); report ACTUAL results.
Do not break Stage 1. Do not implement extraction/OCR/transcription/AI.

- [ ] 1. Config + exceptions
  - [ ] 1.1 Add `max_upload_size_mb` (env `MAX_UPLOAD_SIZE_MB`, default 25) to Settings.
  - [ ] 1.2 Add `MAX_UPLOAD_SIZE_MB` to `backend/.env.example`.
  - [ ] 1.3 Add `BadRequestError` (400) to `app/core/exceptions.py`.
  - _Requirements: 8.1, 1.3, 1.4, 1.5, 1.6_

- [ ] 2. Storage extension (non-breaking)
  - Extend `Storage` Protocol + `LocalStorage` with `put_stream`, `delete`, `open`.
  - Keep existing `put`/`path_for`/`exists` intact.
  - SQLite FK pragma listener in `database.py`.
  - _Requirements: 7.1, 7.2, 7.4, 7.5, 5.2_

- [ ] 3. Evidence model + migration
  - [ ] 3.1 `app/modules/evidence/models.py` — `Evidence` (case_id FK CASCADE, index).
  - [ ] 3.2 `alembic/versions/0002_create_evidence.py` (down_revision 0001).
  - [ ] 3.3 Register evidence model in `alembic/env.py`.
  - [ ] 3.4 Verify `alembic upgrade head` on a fresh DB.
  - _Requirements: 1.1, 6.2_

- [ ] 4. Validation module
  - `app/modules/evidence/validation.py` — extension + magic-byte signature +
    modality resolution; supported-format registry.
  - _Requirements: 1.5, 1.6_

- [ ] 5. Schemas
  - `app/modules/evidence/schemas.py` — `EvidenceType`, `EvidenceOut`, `EvidenceList`.
    No storage_path exposed.
  - _Requirements: 1.7_

- [ ] 6. Repository
  - `create`, `get_scoped(case_id, id)`, `list_for_case`, `delete`, `count_by_hash`.
  - _Requirements: 2.*, 3.*, 5.*, 6.1_

- [ ] 7. Service
  - Upload (validate, size/empty guard, stream to storage, record, orphan cleanup),
    get_scoped, download data, delete (+ blob cleanup when unreferenced),
    cleanup_case_blobs.
  - _Requirements: 1.*, 3.*, 4.*, 5.*, 6.3, 7.6_

- [ ] 8. Router + mount
  - Endpoints under `/api/cases/{case_id}/evidence`; mount in `app/main.py`.
  - _Requirements: 1.*, 2.*, 3.*, 4.*, 5.*_

- [ ] 9. Case-delete blob cleanup hook (additive)
  - `CaseService.delete` calls evidence `cleanup_case_blobs` best-effort.
  - _Requirements: 6.3_

- [ ] 10. Backend tests
  - Unit: validation matrix, sha256, storage stream/delete.
  - Integration: upload per modality, reject unsupported/oversized/empty/bad-signature,
    list, get, download, delete+cleanup, isolation, invalid case id, missing blob.
  - Update `conftest.py` (model import, temp storage root, fixtures).
  - Run pytest + ruff; report actual results.
  - _Requirements: 9.1, 9.2, 9.3_

- [ ] 11. Frontend types + API client
  - `lib/types/evidence.ts`, `lib/api/evidence.ts`, `apiUpload` in `client.ts`.
  - _Requirements: 1.*, 2.*, 4.*, 5.*_

- [ ] 12. Frontend Evidence section
  - `components/evidence/evidence-section.tsx`, `file-type-icon.tsx`; mount in case
    detail page. Drag/drop, browse, multi-file, progress, feedback, list, download,
    delete w/ confirm, empty state. Dark theme.
  - Run typecheck + lint + build; report actual results.
  - _Requirements: 5.5, frontend design language_

> Restrictions: no OCR/extraction/transcription/AI; no create_all() as a migration
> substitute; no DB resets; no hardcoded secrets; preserve SQLite/Postgres support.
