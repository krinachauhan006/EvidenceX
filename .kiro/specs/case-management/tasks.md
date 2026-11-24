# Case Management — Tasks

Implementation plan for Stage 0 (foundation) + Stage 1 (case management).
Execute top to bottom in small, verifiable steps. Tests ship WITH the code, not
after. Run tests + lint after implementation and report ACTUAL results. Stop on a
blocking error. Do not modify unrelated modules.

- [ ] 1. Backend project scaffold (Stage 0)
  - Create `backend/pyproject.toml` (fastapi, uvicorn, sqlalchemy>=2, pydantic>=2,
    pydantic-settings, alembic, psycopg[binary], python-multipart; dev: pytest,
    httpx, ruff).
  - Create `backend/.env.example` (DATABASE_URL, APP_ENV, STORAGE_ROOT, CORS_ORIGINS,
    GEMINI_API_KEY placeholder).
  - Create `docker-compose.yml` with a Postgres service for local dev.
  - Create `backend/.gitignore` and root `.gitignore` (.env, __pycache__, node_modules,
    .next, storage dir).
  - _Requirements: 8.4_

- [ ] 2. Core infrastructure (Stage 0)
  - [ ] 2.1 `app/core/config.py` — Settings via pydantic-settings (no secrets in code).
  - [ ] 2.2 `app/core/database.py` — engine, SessionLocal, `Base`, `get_db` dependency.
  - [ ] 2.3 `app/core/exceptions.py` — `EvidenceXError`, `NotFoundError` + handlers.
  - [ ] 2.4 `app/core/logging.py` — structured logging, never logs secrets.
  - [ ] 2.5 `app/main.py` — app factory, CORS, handlers, `GET /health` (service + DB ping).
  - _Requirements: 8.1, 8.4_

- [ ] 3. Local storage stub (Stage 0)
  - `app/storage/local_store.py` — `Storage` protocol + `LocalStorage`
    (content-addressed layout under STORAGE_ROOT). Path derived ONLY from content
    hash; reject traversal. Stub for later specs; not wired to endpoints yet.
  - _Requirements: 8.5, NFR path-safety_

- [ ] 4. Alembic setup (Stage 0)
  - Initialize `backend/alembic/`; `env.py` points at `Base.metadata` + settings URL.
  - _Requirements: 8.2_

- [ ] 5. cases ORM model + migration
  - [ ] 5.1 `app/modules/cases/models.py` — `Case` (UUID pk, title, description,
    status, created_at, updated_at). ON DELETE CASCADE convention documented for
    future owned tables.
  - [ ] 5.2 Alembic migration: create `cases` + index `(status, updated_at desc)`.
  - [ ] 5.3 Verify `alembic upgrade head` on a fresh DB.
  - _Requirements: 1.1, 5.1, 6.3, 8.2_

- [ ] 6. cases schemas
  - `app/modules/cases/schemas.py` — `CaseStatus`, `CaseCreate`, `CaseUpdate`,
    `CaseOut`, `CaseList`; title validator (trim, non-empty, max 200).
  - _Requirements: 1.2, 1.3, 4.3_

- [ ] 7. cases repository + service + router
  - [ ] 7.1 `repository.py` — `create`, `get`, `list` (status filter, limit/offset,
    total), `update`, `delete`. Default list excludes archived. Scoped-query pattern.
  - [ ] 7.2 `service.py` — orchestration, 404 handling, archive semantics,
    updated_at refresh, delete.
  - [ ] 7.3 `router.py` — POST, GET list, GET one, PATCH, POST archive, DELETE;
    mount under `/api/cases` in the app.
  - _Requirements: 1.1, 1.4, 2.*, 3.*, 4.*, 5.*, 6.*, 7.3_

- [ ] 8. Backend tests (ship with code)
  - [ ] 8.1 `tests/fixtures/` — DB fixture, `get_db` override, `TestClient` client.
  - [ ] 8.2 `tests/unit/` — title validation, archive filtering, pagination math.
  - [ ] 8.3 `tests/integration/` — all six endpoints incl. 404/422, archive filter,
    delete, data-isolation structural test.
  - [ ] 8.4 Run `pytest` and `ruff check`; report ACTUAL results; stop on blocking error.
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

- [ ] 9. Frontend scaffold (Stage 0)
  - Init Next.js App Router + TS + Tailwind + shadcn/ui + Lucide.
  - Dark navy/charcoal theme tokens (amber/neutral/green semantics reserved).
  - `lib/api/client.ts` base client; `lib/types/case.ts` types mirroring schemas.
  - `app/(dashboard)/layout.tsx` shell (sidebar/nav).
  - _Requirements: 8.3, frontend design language_

- [ ] 10. Cases UI
  - [ ] 10.1 `lib/api/cases.ts` typed functions for all six endpoints.
  - [ ] 10.2 `app/(dashboard)/cases/page.tsx` — list, empty state, pagination, new-case.
  - [ ] 10.3 `components/cases/case-form.tsx` — create/edit, required-title validation.
  - [ ] 10.4 `app/(dashboard)/cases/[caseId]/page.tsx` — detail, edit, archive,
    delete with confirmation.
  - _Requirements: 1.1, 2.*, 3.1, 4.1, 5.1, 6.4_

- [ ] 11. End-to-end verification
  - Start Postgres + backend + frontend; create, list, view, edit, archive, delete a
    case; confirm archived hidden by default, visible with `status=archived`.
  - Re-run `pytest` + `ruff`; report actual results.
  - _Requirements: all_

> Testing policy: tests are written alongside each code task (not deferred). AI is
> not involved in this stage, so no AI mocking is needed yet; the mock pattern is
> introduced at the claim-extraction stage. Never fabricate test results.
