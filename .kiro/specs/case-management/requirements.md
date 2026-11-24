# Case Management — Requirements

## Introduction
Case management is the foundational vertical slice of EvidenceX. A **case** is the
top-level container that owns all evidence, extractions, claims, entities, events,
contradictions, findings, and reports. This spec delivers the full stack for cases
(backend module + migration + frontend screens) and establishes the engineering
baseline (Stage 0) that every later spec depends on.

Scope is deliberately narrow: CRUD-plus-archive for cases. No evidence, no AI. The
goal is a working end-to-end chain that proves the architecture.

## Out of scope
- Evidence upload or processing (evidence-ingestion spec).
- Any AI, claims, or contradictions.
- Multi-user auth, permissions, or sharing (deferred).

## Requirements

### Requirement 1 — Create a case
**User story:** As an investigator, I want to create a new case with a title and
optional description, so that I have a container to organize evidence.

#### Acceptance criteria
1. WHEN a user submits a case with a non-empty title THEN the system SHALL create a
   case with a generated UUID, status `open`, and `created_at`/`updated_at` timestamps.
2. WHEN a user submits a case with an empty or whitespace-only title THEN the system
   SHALL reject the request with a 422 validation error.
3. WHEN a title exceeds 200 characters THEN the system SHALL reject the request with
   a 422 validation error.
4. WHEN a case is created THEN the system SHALL return the full case representation
   including its id.

### Requirement 2 — List cases
**User story:** As an investigator, I want to see all my cases, so that I can choose
which one to work on.

#### Acceptance criteria
1. WHEN a user requests the case list THEN the system SHALL return cases ordered by
   `updated_at` descending.
2. WHEN there are no cases THEN the system SHALL return an empty list (not an error).
3. The list SHALL support pagination via `limit` and `offset` with sane defaults
   (limit default 50, max 200).
4. The list response SHALL include a total count so the UI can paginate.

### Requirement 3 — View a single case
**User story:** As an investigator, I want to open a case and see its details.

#### Acceptance criteria
1. WHEN a user requests an existing case by id THEN the system SHALL return the full
   case representation.
2. WHEN a user requests a non-existent case id THEN the system SHALL return 404.
3. WHEN a user requests a malformed (non-UUID) id THEN the system SHALL return 422.

### Requirement 4 — Update a case
**User story:** As an investigator, I want to edit a case's title, description, and
status.

#### Acceptance criteria
1. WHEN a user updates the title/description of an existing case THEN the system
   SHALL persist the change and refresh `updated_at`.
2. WHEN a user updates status to an allowed value (`open`, `archived`) THEN the
   system SHALL persist it.
3. WHEN a user updates with an invalid status THEN the system SHALL return 422.
4. WHEN a user updates a non-existent case THEN the system SHALL return 404.

### Requirement 5 — Archive a case
**User story:** As an investigator, I want to archive a case I am done with, so that
it is hidden from the default list without being deleted.

#### Acceptance criteria
1. WHEN a user archives a case THEN its status SHALL become `archived`.
2. WHEN listing cases without an explicit status filter THEN archived cases SHALL be
   excluded by default.
3. WHEN listing cases with `status=archived` THEN only archived cases SHALL be returned.
4. Archiving SHALL be reversible (status can be set back to `open`).

### Requirement 6 — Delete a case
**User story:** As an investigator, I want to permanently delete a case, so that I
can remove cases created in error.

#### Acceptance criteria
1. WHEN a user deletes an existing case THEN the system SHALL remove it and return
   204 No Content.
2. WHEN a user deletes a non-existent case THEN the system SHALL return 404.
3. WHEN a case is deleted THEN all records owned by that case (evidence, claims,
   etc. in later stages) SHALL be removed via cascade. In this stage only `cases`
   exists, but the schema SHALL establish ON DELETE CASCADE so later owned tables
   inherit it.
4. The frontend SHALL require explicit confirmation before issuing a delete.

### Requirement 7 — Case-level data isolation
**User story:** As an investigator, I want each case's data kept separate, so that
information never leaks between unrelated cases.

#### Acceptance criteria
1. Every owned record (now and in later stages) SHALL carry a `case_id` and be
   queried scoped to that case.
2. WHEN requesting a resource by id that belongs to a different case THEN the system
   SHALL behave as if it does not exist (404), never returning cross-case data.
3. Repository/service list and get operations SHALL always filter by `case_id` for
   owned entities.

### Requirement 8 — Foundation baseline (Stage 0)
**User story:** As the developer, I want the engineering baseline in place so that
every later spec can build on it.

#### Acceptance criteria
1. WHEN the backend starts THEN `GET /health` SHALL return 200 with service status
   and database connectivity.
2. WHEN `alembic upgrade head` runs against a fresh Postgres THEN it SHALL create
   the `cases` table without error.
3. WHEN the frontend builds THEN it SHALL render a dashboard shell and a cases page
   backed by the typed API client.
4. Configuration SHALL be read from environment variables; no secrets in code.
5. Uploaded-file handling is NOT part of this spec, but the local storage interface
   SHALL exist as a stub (content-addressed, path-traversal-safe) so later specs can
   depend on it.

### Requirement 9 — Tests ship with this stage
**User story:** As the developer, I want this stage covered by tests so regressions
are caught immediately.

#### Acceptance criteria
1. Unit tests SHALL cover title validation, archive semantics, and list
   filtering/pagination logic.
2. Integration tests SHALL cover every endpoint (create/list/get/update/archive/
   delete) against a real Postgres, including 404 and 422 paths.
3. An integration test SHALL assert case-level data isolation (a resource from one
   case is not retrievable via another case's scope — placeholder-ready for owned
   entities).
4. Tests SHALL be deterministic; no external network calls. (No AI in this stage.)
5. Reported results SHALL reflect the actual test-runner output; never fabricated.

## Non-functional requirements
- All endpoints return typed Pydantic responses; no ORM leakage.
- Errors map to HTTP via centralized exception handlers.
- Layering (router -> service -> repository) is respected.
- UUID primary keys; `created_at`/`updated_at` on the `cases` table.
- Secrets only via environment variables; none committed.
- Storage path construction is traversal-safe (derived from content hash, never
  from a user-supplied filename).
