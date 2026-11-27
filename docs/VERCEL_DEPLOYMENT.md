# Deploying EvidenceX on Vercel with managed PostgreSQL and S3 storage

This guide covers the serverless deployment: two Vercel projects (frontend and backend),
a managed PostgreSQL database and an S3-compatible bucket. The Docker deployment in
[`DEPLOYMENT.md`](DEPLOYMENT.md) is unchanged and remains the option with every
processing engine.

**Status.** The code, configuration checks and tests for this deployment are in the
repository (see "What is done in code"). **Nothing has been deployed yet.** The behaviour
on Vercel itself, on the managed database and against a real bucket has not been
observed; the checks in "After deploying" are how to confirm it.

## Architecture

```
Browser ──HTTPS──▶ Vercel project "frontend" (root: frontend/, Next.js)
                     │  pages, scripts, styles
                     └─ rewrites /api/* and /health ──▶ Vercel project "backend"
                                                         (root: backend/, FastAPI, Python 3.12)
                                                           ├─▶ managed PostgreSQL
                                                           └─▶ S3-compatible bucket (evidence files)
```

- The browser only ever talks to the frontend's origin. Next.js forwards `/api/*` and
  `/health` to the backend (`EVIDENCEX_API_ORIGIN`, a server-side variable), so the
  `HttpOnly`, `Secure`, `SameSite=Lax` session cookie is first-party and the CSP allows no
  other origin.
- The backend keeps no state on its own disk: the database holds records and reports, and
  the bucket holds evidence files under their SHA-256 (`aa/bb/<sha256>`).
- Each backend request runs in a Vercel Function: Python 3.12, at most 300 s (Hobby),
  2 GB memory, request bodies up to 4.5 MB
  ([Vercel limits](https://vercel.com/docs/functions/limitations), checked 2026-11-27).

## What works on Vercel and what does not

The backend deployed on Vercel installs only the base dependencies in
`backend/pyproject.toml`. It has no system packages, no `audio` extra and no speech model.

| Capability | On Vercel | Why |
|---|---|---|
| Accounts, sessions, roles, case isolation, CSRF check, audit chain | Works | — |
| Upload with content validation, download, delete | Works up to **4.5 MB per file** | Vercel request-body limit |
| PDF text extraction, page previews | Works | PyMuPDF is a Python wheel |
| OCR of scanned PDF pages | **Not available** (text pages still extract) | Tesseract is a system program |
| Image OCR (photos, scans) | **Not available** | Tesseract |
| Audio transcription | **Not available** | PyAV and faster-whisper are the optional `audio` extra; no model |
| Video frames, frame OCR, soundtrack, frame thumbnails | **Not available** | PyAV, Tesseract |
| CSV, XLSX, e-mail (.eml) extraction | Works | Pure Python |
| Claims, entities, events, possible inconsistencies, timeline, graph, search, "Ask" (rule-based) | Works | — |
| Investigation and graph PDF reports, JSON/GraphML export | Works (reports are stored in the database) | PyMuPDF |
| Gemini (AI claims, drafts) | Only with `GEMINI_API_KEY` and per-case consent; never live-tested | Network service |
| Subprocess isolation with a hard timeout per item | **Not used** (`PROCESSING_ISOLATION=inline`) | No worker processes in a function |
| Items longer than 300 s | Cut off; marked stale after `PROCESSING_STALE_MINUTES`, then retryable | Function duration limit |

A file that needs a missing engine is kept, can still be downloaded, and is marked
**failed — Required component missing** with this explanation: the file type needs an
engine that is not available on this serverless deployment, and it can be processed on a
full installation (Docker or local) connected to the same database and storage. Nothing
crashes and no result is invented.

Larger uploads would need **direct-to-bucket uploads** (presigned URLs, then server-side
validation). That is a separate, unimplemented enhancement; it is not needed for the demo
files (all under 0.5 MB).

## What is done in code (this repository)

| Area | Where |
|---|---|
| S3-compatible storage, local storage still default | `backend/app/storage/s3_store.py`, `factory.py` |
| Start-up checks: S3 settings, Secure cookie in production, Vercel constraints | `backend/app/core/deploy_checks.py` (called from the lifespan in `app/main.py`) |
| `postgres://` / `postgresql://` URLs use psycopg; small checked pool; transaction-pooler mode | `backend/app/core/config.py`, `backend/app/core/database.py` |
| Vercel entry point and Python version | `[tool.vercel] entrypoint = "app.main:app"` in `backend/pyproject.toml`; `backend/.python-version` (3.12) |
| Files never uploaded to Vercel (database, storage, `.env`, venv, tests) | `backend/.vercelignore` |
| Clear message for engines missing on Vercel | `backend/app/modules/processing/runner.py` |
| Same-origin API proxy and same-origin CSP | `frontend/next.config.mjs`, `frontend/lib/api-proxy.mjs` |
| Plain message when the platform refuses a large upload (413) | `frontend/lib/api/client.ts` |
| One-time demo seeding | `backend/app/demo_seed.py`, `python -m app.cli seed-demo` |
| Environment templates (placeholders only) | `deploy/vercel-backend.env.example`, `deploy/vercel-frontend.env.example` |

## What you must do in cloud consoles

1. A **GitHub** repository with this code pushed (already `krinachauhan006/EvidenceX`).
2. A **Vercel** account (Hobby is enough for a hackathon; it is for non-commercial use).
3. A **managed PostgreSQL** database: Supabase (below) or Neon.
4. An **S3-compatible bucket**: Supabase Storage (below), AWS S3, Cloudflare R2 or similar.

### 1. PostgreSQL (Supabase example)

From Supabase's documentation
([connecting to Postgres](https://supabase.com/docs/guides/database/connecting-to-postgres),
checked 2026-11-27):

- Create a project and keep the database password.
- Click **Connect** and copy two strings:
  - **Transaction pooler** (shared pooler, port **6543**) for the Vercel backend. It is
    meant for serverless functions, is reachable over IPv4, and does **not** support
    prepared statements. So also set `DATABASE_TRANSACTION_POOLER=true`.
  - **Session pooler** (port **5432**, same pooler host) for running migrations from your
    computer. The direct connection `db.<ref>.supabase.co` is IPv6-only on the free plan.
- Shared-pooler usernames look like `postgres.<project-ref>`; copy the host from the
  Connect dialog (it cannot be derived from the region). Percent-encode special characters
  in the password.

Neon: the pooled hostname ends in `-pooler` (PgBouncer, transaction mode); use it with
`DATABASE_TRANSACTION_POOLER=true`, and the direct hostname for migrations
([Neon pooling](https://neon.com/docs/connect/connection-pooling)).

### 2. Bucket (Supabase Storage example)

From [Supabase S3 authentication](https://supabase.com/docs/guides/storage/s3/authentication):

- Storage → create a **private** bucket (for example `evidence`). Do not make it public.
- Storage → S3 configuration: copy the **endpoint** (`https://<project-ref>.storage.supabase.co/storage/v1/s3`)
  and the **region**, and generate an **access key pair**.
- These keys give full access to every bucket in the project and bypass row-level security.
  They belong only in the backend's environment variables, never in the frontend or Git.

### 3. Environment variables

**Backend project** (template: `deploy/vercel-backend.env.example`):

| Variable | Value | Required |
|---|---|---|
| `APP_ENV` | `production` | yes |
| `COOKIE_SECURE` | `true` (start-up refuses `false` in production) | yes |
| `DATABASE_URL` | transaction-pooler URL (`postgresql://…:6543/postgres`) | yes |
| `DATABASE_TRANSACTION_POOLER` | `true` with a transaction pooler | yes for Supabase 6543 / Neon pooled |
| `STORAGE_BACKEND` | `s3` (start-up refuses `local` on Vercel) | yes |
| `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | from the bucket | yes |
| `S3_ENDPOINT_URL` | Supabase endpoint; empty only for AWS S3 | yes (non-AWS) |
| `S3_REGION` | the project/bucket region | yes |
| `CORS_ORIGINS` | the frontend origin, e.g. `https://evidencex.vercel.app` (comma-separated, no trailing slash) | yes |
| `PROCESSING_ISOLATION` | `inline` (start-up refuses `subprocess` on Vercel) | yes |
| `MAX_UPLOAD_SIZE_MB`, `MAX_VIDEO_UPLOAD_MB` | `4` (a warning is logged if above 4.5) | recommended |
| `PROCESSING_STALE_MINUTES`, `ANALYSIS_STALE_MINUTES` | `10` | recommended |
| `REGISTRATION_OPEN` | `true` until accounts exist, then `false` | recommended |
| `CLAIM_EXTRACTOR` | `rule_based` | optional |
| `GEMINI_API_KEY` | only if AI is wanted | optional |

`VERCEL=1` is set by Vercel itself and turns on the serverless checks.

**Frontend project** (template: `deploy/vercel-frontend.env.example`):

| Variable | Value |
|---|---|
| `EVIDENCEX_API_ORIGIN` | the backend project's origin, e.g. `https://evidencex-api.vercel.app` (no path) |
| `NEXT_PUBLIC_API_BASE_URL` | **do not set** |

Every value is read at **build time** for the frontend; redeploy after changing it.

### 4. Run the database migrations (from your computer, once per release)

Use the **session-mode** (or direct) URL, not the transaction pooler. PowerShell, in
`backend/` with the project's virtual environment:

```powershell
cd backend
$env:DATABASE_URL = "postgresql://postgres.<ref>:<password>@<pooler-host>:5432/postgres?sslmode=require"
.venv\Scripts\python.exe -m alembic current
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m alembic current     # must print 0007_phase2 (head)
Remove-Item Env:DATABASE_URL
```

The backend refuses to start in production until the database is at head.

### 5. Create the backend project

Vercel → Add New → Project → import the GitHub repository:

- **Root Directory:** `backend`
- Framework: detected as FastAPI from `pyproject.toml`; entry point `app.main:app`
  (`[tool.vercel]`), Python 3.12 (`.python-version`).
- Add the backend variables (Production; add Preview too if you use preview deployments).
- Deploy, then open `https://<backend>.vercel.app/health`.

### 6. Create the frontend project

Import the same repository again as a second project:

- **Root Directory:** `frontend`, framework **Next.js**.
- Add `EVIDENCEX_API_ORIGIN`. Deploy.
- Put the frontend's final URL in the backend's `CORS_ORIGINS` and **redeploy the
  backend**. Preview URLs of the frontend change per deployment; add each one you use, or
  test only on the production URL.

Command-line alternative (after `npm i -g vercel` and `vercel login`): run `vercel link`
and `vercel deploy --prod` inside `backend/` and inside `frontend/`. Running the CLI from
`backend/` respects `backend/.vercelignore`, so `backend/var/` (the local database and
evidence) is never uploaded.

### 7. After deploying: verify

1. `https://<frontend>/health` (through the proxy) shows
   `{"status":"ok","database":"ok","schema":{"revision":"0007_phase2","expected":"0007_phase2","up_to_date":true}}`.
2. Response headers on `https://<frontend>/` include `Content-Security-Policy` without any
   other origin, and `/api/auth/me` answers 401 with `Cache-Control: no-store`.
3. Register, sign in, reload the page: you stay signed in (the cookie survives the proxy).
4. Create a case, upload `pallet_ledger.csv`, process it: it completes. Upload
   `gate_log_photo.png`: it fails with the serverless explanation (expected).
5. Download the CSV again and compare; check in the bucket that an object exists under
   `aa/bb/<sha256>`.
6. Backend logs (Vercel → Logs) show no `configuration:` warnings and no tracebacks.

### 8. MANDATORY: verify background tasks on the preview deployment

> **Do not skip this step.** Evidence processing and case analysis run as FastAPI
> `BackgroundTasks`. The API returns `202 Accepted` first and does the work *after* the
> HTTP response has been sent. On serverless platforms, work after the response can be
> cut off when the function instance is frozen or recycled. This has **not** been verified
> on a real Vercel deployment. Until this test passes, do not describe background
> processing as production-verified.

Run this on a **preview** deployment, before you rely on production:

1. Sign in and **create a new test case** (for example "Background task check").
2. **Upload one small supported file** that needs no OCR. Use a CSV (e.g.
   `sample-evidence/demo-missing-shipment/pallet_ledger.csv`) or a text-based PDF (e.g.
   `delivery_receipt.pdf`). Do not use an image, audio or video file for this test.
3. **Trigger processing** from the case's evidence page, or with
   `POST /api/cases/{case_id}/evidence/process-pending`.
   The request returns `202` straight away.
4. Without retrying anything, **wait and refresh**. Confirm the file reaches `completed`
   and does not stay `pending` or `processing`. This proves the task kept running after
   the response was sent.
5. **Trigger analysis** from the case page, or with `POST /api/cases/{case_id}/analysis`. Confirm
   `GET /api/cases/{case_id}/analysis/latest` reports a finished run, not a running or
   stalled one.
6. **Confirm the results are persisted.** Reload the page, then sign out and back in, and
   check all of the following:
   - the extracted evidence is visible (segments of the uploaded file);
   - claims appear;
   - the timeline shows entries;
   - a search for a word from the file returns results.
7. **Check the Vercel function logs** (Vercel → backend project → Logs) for the processing
   and analysis requests. Look for `processing completed` and `analysis completed` lines.
   Failure signs are tracebacks, `Task timed out`, a function ending before those lines
   appear, or no log line at all after the `202` response.

**Result:**

- **All checks pass:** background processing is verified for this deployment. Record the
  date and the deployment URL you tested.
- **Any check fails** (an item stays `processing`, analysis never finishes, or the logs
  show the function stopping early): background tasks are **not** reliable on this
  deployment. Do not present the site as production-ready. Process evidence from a full
  installation connected to the same database and bucket (see the seeding section below),
  and note the limitation for judges.

## Seed the Missing Shipment demonstration case

The demo case should be processed **once on a full installation**, so that OCR, video and
audio steps run. Then it is stored in the same cloud database and bucket the deployed site
reads. Seeding is never automatic and is safe to re-run (an existing case with the same
title and owner is left untouched).

On your computer (Tesseract installed; for audio, `pip install -e ".[audio]"` and
`python -m app.tools.fetch_whisper_model --size base`):

1. Register the owner account and, for judges, a viewer account on the live site.
2. In `backend/`, point the CLI at the cloud resources for this shell only:

   ```powershell
   $env:DATABASE_URL = "<session-mode URL>"
   $env:STORAGE_BACKEND = "s3"; $env:S3_BUCKET = "evidence"
   $env:S3_ENDPOINT_URL = "https://<ref>.storage.supabase.co/storage/v1/s3"; $env:S3_REGION = "<region>"
   $env:S3_ACCESS_KEY_ID = "<key id>"; $env:S3_SECRET_ACCESS_KEY = "<secret>"
   .venv\Scripts\python.exe -m app.cli seed-demo --owner owner@example.org --viewer judge@example.org --dry-run
   .venv\Scripts\python.exe -m app.cli seed-demo --owner owner@example.org --viewer judge@example.org --yes
   ```

   The command prints the target (`database: postgresql…; evidence storage: s3 bucket
   'evidence'`), then each file's real processing status and the analysis counts.
3. Sign in as the owner on the live site. Review the proposed event under **Events** and
   confirm it if you agree. Then generate the investigation and graph reports. These are
   human review decisions, so the script does not make them.
4. Sign in as the judge: the case is visible read-only (viewer role, enforced on the server).
5. Close the shell (or remove the variables) so the credentials do not linger.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Backend fails at start; log says "configuration is not valid" | A listed setting is missing or wrong; the message names it (never its value). |
| Log `SchemaNotReadyError … run 'alembic upgrade head'` | Migrations not applied to this database: step 4. |
| `prepared statement … already exists` / `does not exist` | Transaction pooler without `DATABASE_TRANSACTION_POOLER=true`. |
| Database connection times out or "network unreachable" | Using Supabase's IPv6-only direct host; use the pooler host. |
| `403 cross-origin request refused` on every write | The frontend origin is missing from `CORS_ORIGINS` (exact scheme and host, no slash). |
| Signed in, then immediately signed out | `NEXT_PUBLIC_API_BASE_URL` is set (browser calls the backend cross-site); remove it and redeploy the frontend. |
| `503 Evidence storage is temporarily unavailable` | Bucket, keys, endpoint or region wrong; backend logs show the provider error code (e.g. `AccessDenied`, `NoSuchBucket`). |
| Upload fails "larger than this server accepts" | Over Vercel's 4.5 MB limit. |
| Item stays "processing" | The 300 s function limit cut it off; after `PROCESSING_STALE_MINUTES` retry it. |
| "Required component missing" on images, audio, video | Expected on Vercel; seed or process those files from a full installation. |

## Security notes for this deployment

- Secrets live only in Vercel's environment variables. The repository contains placeholders
  only; `.env*` files and `backend/var/` are git-ignored and excluded by `.vercelignore`.
- Logs contain setting names and provider error codes, never values, credentials or raw
  provider messages.
- `/api/*` responses carry `Cache-Control: no-store` (previews: `private`), so Vercel's
  CDN does not cache case data on the rewrite; check `x-vercel-cache` after deploying.
- The failed-sign-in throttle is per function instance (in memory), so it is weaker on
  Vercel than with Docker's single process, and there is no proxy rate limit (Caddy is not
  used here). Consider Vercel's firewall rules for `/api/auth/login`.
- Optional hardening: restrict the backend to traffic from the frontend proxy with a shared
  secret header ([Vercel docs](https://vercel.com/docs/rewrites)). Not implemented.
- AGPL-3.0: tag and push the exact deployed commit; the footer links to the source.

---
EvidenceX · Copyright (C) 2026 [COPYRIGHT HOLDER: TO BE CONFIRMED] · GNU AGPL-3.0 ([LICENSE](../LICENSE))
