# Case Management — Design

## Overview
This design covers Stage 0 (foundation baseline) and Stage 1 (case management). It
establishes the backend app structure, database/migration tooling, storage stub,
and the frontend shell, then implements the `cases` feature as a full vertical slice.

## Architecture fit
- Backend module `app/modules/cases/` following the standard layering:
  `router -> service -> repository`, with distinct `models.py` (ORM) and
  `schemas.py` (Pydantic). See `architecture.md`.
- Frontend screens under `app/(dashboard)/cases/` using the typed API client in
  `lib/api/`.

## Backend components

### Core (Stage 0)
- `app/core/config.py` — `Settings` via `pydantic-settings`: `DATABASE_URL`,
  `APP_ENV`, `STORAGE_ROOT`, CORS origins. Loaded once, injected where needed.
- `app/core/database.py` — SQLAlchemy 2.0 engine + `SessionLocal`; FastAPI
  dependency `get_db()` yielding a scoped session.
- `app/core/exceptions.py` — domain exception hierarchy
  (`EvidenceXError`, `NotFoundError`, `ValidationError`) + FastAPI exception
  handlers mapping them to 404/422/500.
- `app/core/logging.py` — structured logging config; never logs secrets.
- `app/main.py` — app factory: CORS, exception handlers, router mounting,
  `GET /health` (returns service + DB ping).
- `app/storage/local_store.py` — `Storage` protocol + `LocalStorage` implementation
  (content-addressed path layout under `STORAGE_ROOT`). Stub only; used by later specs.

### cases module (Stage 1)
- `models.py` — `Case` ORM model.
- `schemas.py` — `CaseCreate`, `CaseUpdate`, `CaseOut`, `CaseList`.
- `repository.py` — `CaseRepository`: `create`, `get`, `list` (with status filter,
  limit/offset, total count), `update`, `delete`.
- `service.py` — `CaseService`: business rules (title validation beyond schema,
  archive semantics, not-found handling, delete).
- `router.py` — endpoints:
  - `POST   /api/cases`            -> 201 CaseOut
  - `GET    /api/cases`            -> 200 CaseList (query: status, limit, offset)
  - `GET    /api/cases/{case_id}`  -> 200 CaseOut | 404
  - `PATCH  /api/cases/{case_id}`  -> 200 CaseOut | 404
  - `POST   /api/cases/{case_id}/archive` -> 200 CaseOut | 404
  - `DELETE /api/cases/{case_id}`  -> 204 | 404

## Data isolation
- Every owned entity (added in later stages) carries `case_id` and is always queried
  scoped to its case. Fetch-by-id for an owned entity that belongs to a different
  case returns 404 — never cross-case data.
- Foreign keys from owned tables to `cases` use `ON DELETE CASCADE`, so deleting a
  case removes all its data. Only `cases` exists in this stage; the cascade
  convention is established now for later tables to inherit.

## Data model

### `cases` table
| column      | type        | notes                                  |
|-------------|-------------|----------------------------------------|
| id          | UUID (pk)   | server-generated default               |
| title       | varchar(200)| not null, non-empty (validated)        |
| description | text        | nullable                               |
| status      | varchar(16) | enum: `open` \| `archived`, default `open` |
| created_at  | timestamptz | not null, default now()                |
| updated_at  | timestamptz | not null, default now(), on-update now |

Index on `(status, updated_at desc)` to back the default list query.

### Pydantic schemas
```
CaseCreate:  title: str (1..200, trimmed, non-empty), description: str | None
CaseUpdate:  title: str | None, description: str | None, status: CaseStatus | None
CaseOut:     id, title, description, status, created_at, updated_at
CaseList:    items: list[CaseOut], total: int, limit: int, offset: int
CaseStatus:  Literal["open", "archived"]
```
Title validation: strip whitespace; reject empty after strip (Requirement 1.2),
enforce max length (1.3).

## Migrations
- Alembic initialized under `backend/alembic/`.
- First migration creates the `cases` table and the composite index.
- `alembic upgrade head` must run cleanly on a fresh DB (Requirement 6.2).

## Frontend components
- `app/(dashboard)/layout.tsx` — shell with sidebar/nav.
- `app/(dashboard)/cases/page.tsx` — list cases (Server Component fetch), empty
  state, pagination, "New case" action.
- `app/(dashboard)/cases/[caseId]/page.tsx` — case detail: title, description,
  status, edit + archive actions.
- `components/cases/case-form.tsx` — create/edit form (Client Component), shadcn/ui
  inputs, client-side required-title validation mirroring the server.
- `lib/api/cases.ts` — typed client functions for all five endpoints.
- `lib/types/case.ts` — TS types mirroring the Pydantic schemas (later: generated
  from OpenAPI).

## Error handling
- Domain exceptions raised in service/repository, mapped centrally:
  `NotFoundError -> 404`, validation -> 422 (FastAPI/Pydantic native), unexpected -> 500.
- Frontend API client surfaces typed errors; forms show field-level messages for 422
  and a toast for 404/500.

## Testing (ships WITH this stage)
Framework: `pytest`. AI not involved in this stage. Tests are deterministic and
make no external network calls. Reported results reflect actual runner output.

- Unit (`tests/unit/`):
  - Title validation: empty/whitespace rejected, >200 chars rejected, trimmed.
  - Archive semantics: default list excludes archived; `status=archived` returns only archived.
  - List pagination math: limit default/cap, offset, total count.
- Integration (`tests/integration/`) against a real Postgres (docker-compose or a
  test DB; schema applied via Alembic):
  - `POST /api/cases` happy path (201) + empty title (422) + long title (422).
  - `GET /api/cases` list ordering, pagination, empty list, status filter.
  - `GET /api/cases/{id}` found (200), missing (404), malformed id (422).
  - `PATCH /api/cases/{id}` update (200), invalid status (422), missing (404).
  - `POST /api/cases/{id}/archive` (200) + missing (404).
  - `DELETE /api/cases/{id}` (204) + missing (404).
  - Data isolation: a case fetched outside its own scope is not returned
    (structural test establishing the scoped-query pattern for owned entities).
- `tests/fixtures/`: session-scoped DB fixture + `get_db` override so a test
  session is injected (DI). A `client` fixture wraps the FastAPI app with TestClient.

## Risks / decisions
- **Single-user, no auth** for the MVP — acceptable for the hackathon; documented as
  deferred. Endpoints are structured so an auth dependency can be added later without
  reshaping the module.
- **Soft archive, no hard delete** — preserves data and matches the audit-oriented
  product posture.
- **Storage stub now** — avoids rework when evidence-ingestion lands; the interface
  is the contract.
