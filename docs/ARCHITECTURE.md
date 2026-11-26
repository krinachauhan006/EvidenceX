# Architecture

A modular monolith with two deployables that talk over REST.

```
frontend/ (Next.js 14, TypeScript)          backend/ (FastAPI, Python ≥ 3.11)
  app/            routes (App Router)          app/main.py        app factory, CORS, CSRF check, headers
  components/     UI, viewers, landing         app/core/          config, database, schema state, errors
  lib/api/        typed API client             app/modules/
  lib/types/      mirrors backend schemas        auth/            accounts, sessions, roles, members
                                                 cases/           cases, consent
                                                 evidence/        upload, validation, preview
                                                 processing/      extractors (PDF, image OCR, audio,
                                                                  video, CSV/XLSX, e-mail), runner
                                                 analysis/        claims, entities, events, timeline,
                                                                  contradictions, search/ask, reports,
                                                                  graph export, audit chain
                                               app/ai/            Gemini client + versioned prompts
                                               app/storage/       content-addressed file store
                                               alembic/           migrations 0001–0007
```

## Pipeline
Upload (magic-byte validation, SHA-256 storage) → processing in a subprocess per item
(segments with physical locators) → claim extraction (rule-based; Gemini only with key
and case consent) → entities and proposed events → comparisons inside confirmed events
(possible inconsistencies with alternatives) → human review (audited, hash-chained) →
reports (narrative PDF, graph PDF, JSON, GraphML).

## Provenance model
Every claim references exactly one extraction segment. Every segment carries its locator:
PDF/image page and box, audio start/end, video frame time and region, CSV row/column,
XLSX sheet/cell, e-mail header or part. Findings reference the claims they rest on.

## Deployment shape
In production one Caddy reverse proxy serves a single HTTPS origin: `/api/*` and
`/health` go to the API, everything else to the Next.js server. Caddy also rate-limits
sign-in and registration. The API runs one uvicorn worker (in-process background tasks
and the in-memory sign-in throttle) and refuses to start on a database with pending
migrations. Security headers: `frontend/lib/csp.mjs` for pages, `app/main.py` for API
responses. Details and the untested status of the images: `DEPLOYMENT.md`.

## API
FastAPI serves interactive OpenAPI documentation at `/docs` and the schema at
`/openapi.json` on the API host. All routes except `/health`, `POST /api/auth/register`
and `POST /api/auth/login` require a session.

The project conventions and invariants used while building with Kiro are in
`.kiro/steering/`, and the feature specifications are in `.kiro/specs/`.

---
EvidenceX · Copyright (C) 2026 Krina R. Chauhan · GNU AGPL-3.0 ([LICENSE](../LICENSE))
