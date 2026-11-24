# EvidenceX — Coding Standards

## General
- Clarity over cleverness. Small, cohesive functions. Explicit over implicit.
- Solve the task at hand; do not add speculative abstraction or configurability.
- Match existing patterns in the module you are editing before introducing new ones.

## Python (backend)
- Target Python 3.11+. Full type hints on all public functions and methods.
- Pydantic v2 for all request/response and AI output schemas.
- SQLAlchemy 2.0 style (typed `Mapped[...]` columns, `select()` queries).
- Layering is strict: router -> service -> repository. Routers never touch the ORM
  directly; repositories never contain business logic.
- Pydantic schemas (`schemas.py`) and ORM models (`models.py`) are distinct types.
  Never return ORM objects directly from endpoints.
- Config via `pydantic-settings`, read from environment. No secrets in code.
- Errors: raise domain exceptions from `app/core/exceptions.py`; map to HTTP in
  one place via exception handlers. No bare `except:`.
- Logging via `app/core/logging.py`. Never log secrets, tokens, or raw file bytes.
- Formatting/linting: `ruff` (lint + format). Keep imports ordered.
- Naming: `snake_case` functions/vars, `PascalCase` classes, `UPPER_SNAKE` constants.

## AI code
- All model calls go through `app/ai/gemini_client.py`. No ad-hoc SDK calls elsewhere.
- Every call declares an output Pydantic schema and validates against it.
- Prompts live as versioned templates in `app/ai/prompts/`; do not inline large prompts.
- Never trust model output for control flow without validation.

## TypeScript (frontend)
- Strict mode on. No `any`; use `unknown` + narrowing when a type is genuinely open.
- Next.js App Router; Server Components by default, Client Components only when
  interactivity requires it (`"use client"`).
- Tailwind for styling; shadcn/ui for primitives; Lucide React for icons.
- API access goes through the typed client in `lib/api/`; components do not call
  `fetch` directly.
- Shared types in `lib/types/` mirror backend schemas (ideally generated from OpenAPI).
- Naming: `PascalCase` components, `camelCase` functions/vars, `kebab-case` files
  for route segments.

## Testing (tests ship WITH every stage — not deferred)
- Every implementation stage lands with unit AND integration tests in the same
  change. Code is never considered done until its tests pass.
- Keep code testable via dependency injection (DB session, AI client, storage).
- Unit tests are deterministic and mock the AI client. Integration tests run
  against a real Postgres.
- AI responses are ALWAYS mocked in tests. Never call the real Gemini API from tests.
- Never fabricate test results, pass/fail status, or accuracy/precision metrics.
  Report only what the test runner actually produced.
- Priority coverage areas (test these first and thoroughly):
  1. File validation and upload security (magic bytes, size, path traversal).
  2. Extraction and segment provenance (locators present and correct).
  3. Claim-to-source relationships (every claim anchored to a valid segment).
  4. Temporal normalization and precision preservation.
  5. Contradiction detection.
  6. Case-level data isolation (no cross-case leakage).
  7. AI structured-output validation (schema enforcement + repair/fail path).
  8. Human review and audit history.
- Test layout: `backend/tests/unit/`, `backend/tests/integration/`,
  `backend/tests/fixtures/`. Use `pytest`.

## Frontend design language
- This is a premium, professional investigative intelligence platform, NOT a
  generic chatbot. No chat-bubble UI as the primary surface.
- Palette: dark navy / charcoal base. Restrained **amber** highlights ONLY for
  potential inconsistencies/contradictions. **Neutral** styling for unresolved
  findings. **Green** for completed processing. Use color sparingly and semantically.
- Target workspace layout (built incrementally, not all at once):
  - Left panel: evidence library + per-file processing status.
  - Center panel: original evidence viewer (PDF/image/audio).
  - Right panel: extracted claims and findings.
  - Bottom panel: chronological investigation timeline.
- Clicking a claim navigates to its exact source location (PDF page, image region,
  or audio timestamp) where supported.
- Define component structure and interactions before implementing complex screens.

## Git
- Small, focused commits with clear messages. Never commit secrets or `.env`.
- Commit only when asked.

## Database / migrations
- Every schema change ships with an Alembic migration. Never edit a DB by hand.
- UUID primary keys. `created_at`/`updated_at` timestamps on persistent entities.
- Foreign keys enforced. Status columns use constrained enums.
