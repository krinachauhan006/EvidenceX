# Evidence Ingestion — Requirements

## Introduction
Stage 2 adds evidence ingestion and management to EvidenceX. Evidence is any
uploaded file (document, image, or audio) that belongs to exactly one case. This
stage covers upload with strict validation, secure content-addressed local
storage, listing/retrieval/download, and deletion — plus the case-detail Evidence
UI. It deliberately stops before any content processing.

## Out of scope (belongs to Stage 3+)
- PDF text extraction, image OCR, audio transcription.
- AI claim extraction, Gemini integration.
- Background processing workers. (Records are created with status `pending`; no
  processing runs yet.)

## Supported formats (initial)
- Document: `.pdf` (application/pdf)
- Image: `.png`, `.jpg`/`.jpeg`, `.webp`
- Audio: `.wav`, `.mp3`, `.m4a`

File type is validated by extension AND by actual content signature (magic bytes)
where practical. The client-supplied MIME type and filename are never trusted on
their own.

## Requirements

### Requirement 1 — Upload evidence to a case
**User story:** As an investigator, I want to upload a file to a specific case so
that it becomes part of that case's evidence set.

#### Acceptance criteria
1. WHEN a user uploads a supported, non-empty, within-limit file to an existing
   case THEN the system SHALL store the file content-addressed and create an
   `evidence` record with status `pending`, returning the record (201).
2. WHEN the target case does not exist THEN the system SHALL return 404 and store
   nothing.
3. WHEN the file is empty (0 bytes) THEN the system SHALL reject it (400) and store
   nothing.
4. WHEN the file exceeds the configured size limit THEN the system SHALL reject it
   (400) and store nothing.
5. WHEN the file's extension is unsupported THEN the system SHALL reject it (400).
6. WHEN the file's actual content signature does not match a supported type (or
   contradicts its extension) THEN the system SHALL reject it (400).
7. The response SHALL include: id, case_id, original_filename, evidence_type,
   mime_type, byte_size, sha256, processing_status, processing_error, uploaded_at.
   It SHALL NOT include the absolute storage path.

### Requirement 2 — List evidence for a case
**User story:** As an investigator, I want to see all evidence in a case.

#### Acceptance criteria
1. WHEN a user lists evidence for an existing case THEN the system SHALL return that
   case's evidence ordered by `uploaded_at` descending.
2. WHEN the case has no evidence THEN the system SHALL return an empty list.
3. WHEN the case does not exist THEN the system SHALL return 404.
4. The listing SHALL only ever contain evidence belonging to the requested case.

### Requirement 3 — Retrieve evidence metadata
**User story:** As an investigator, I want to view the metadata of one evidence item.

#### Acceptance criteria
1. WHEN a user requests an existing evidence item via its owning case THEN the
   system SHALL return its metadata (200).
2. WHEN the evidence id does not exist THEN the system SHALL return 404.
3. WHEN the evidence exists but belongs to a DIFFERENT case than the one in the
   path THEN the system SHALL return 404 (never cross-case data).

### Requirement 4 — Download / securely access the file
**User story:** As an investigator, I want to download an uploaded file.

#### Acceptance criteria
1. WHEN a user downloads existing evidence via its owning case THEN the system SHALL
   stream the original bytes with the correct content type and the original
   filename as the download name.
2. The file SHALL be served as an attachment / non-executable; the server SHALL
   never execute or interpret the file.
3. WHEN the evidence belongs to a different case than the path case THEN the system
   SHALL return 404.
4. WHEN the stored blob is missing on disk THEN the system SHALL return 404 with a
   clear error, not a server crash.

### Requirement 5 — Delete evidence
**User story:** As an investigator, I want to permanently delete an evidence item.

#### Acceptance criteria
1. WHEN a user deletes existing evidence via its owning case THEN the system SHALL
   remove the record and return 204.
2. The stored blob SHALL be removed from disk when no other evidence record (in any
   case) references the same content hash. Shared content is not deleted while
   still referenced.
3. WHEN the evidence belongs to a different case than the path case THEN the system
   SHALL return 404 and delete nothing.
4. WHEN the evidence id does not exist THEN the system SHALL return 404.
5. The frontend SHALL require explicit confirmation before deleting.

### Requirement 6 — Case-level isolation
**User story:** As an investigator, I need evidence kept strictly within its case.

#### Acceptance criteria
1. Every evidence operation (get, download, delete) SHALL be scoped by both
   `case_id` and `evidence_id`; a mismatch SHALL behave as not-found (404).
2. Deleting a case SHALL cascade-delete its evidence records (FK ON DELETE CASCADE).
3. Deleting a case SHALL also remove orphaned blobs for that case's evidence where
   no remaining record references them. (Blob cleanup is best-effort and MUST NOT
   block or corrupt the case delete.)

### Requirement 7 — Secure storage
**User story:** As the platform, I must store untrusted files safely.

#### Acceptance criteria
1. Files SHALL be stored under content-addressed names derived ONLY from the SHA-256
   of the content, never from the user-supplied filename.
2. Path traversal SHALL be impossible: no storage path is constructed from user
   input; hash-derived paths are validated to stay under the storage root.
3. The original filename SHALL be preserved as metadata only.
4. Duplicate content (same hash) uploaded again SHALL be handled safely: the blob is
   written once; each upload still yields its own evidence record.
5. Large files SHALL be hashed and written in a streaming/chunked manner, not held
   wholly in memory where avoidable.
6. On any failure, the system SHALL NOT leave an orphaned blob without a record, nor
   a record without its blob. (Write blob first, then commit record; on record
   failure, remove the just-written blob if unreferenced.)
7. API keys and secrets SHALL come from the environment only.

### Requirement 8 — Configuration
1. The maximum upload size SHALL be configurable via environment
   (`MAX_UPLOAD_SIZE_MB`) with a sensible default of 25 MB.

### Requirement 9 — Tests ship with this stage
1. Unit + integration tests SHALL cover: supported uploads per modality, unsupported
   rejection, oversized rejection, empty rejection, signature/MIME mismatch,
   listing, metadata retrieval, download, deletion, case isolation, invalid case id,
   storage-failure handling, and SHA-256 correctness.
2. Existing Stage 1 (case management) tests SHALL continue to pass unchanged.
3. Reported results SHALL reflect the actual test runner output; never fabricated.

## Non-functional / invariant alignment
- Uploaded content is never executed (safety invariant 16).
- Magic-byte validation, not extension/MIME alone (invariant 14, 15).
- Hash-derived, traversal-safe paths (invariant 17).
- Layering router -> service -> repository; Pydantic out, no ORM leakage.
- SQLite/Postgres portability preserved via the shared `GUID` type.
