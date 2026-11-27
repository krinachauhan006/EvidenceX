# Deploying EvidenceX

This page covers the Docker deployment (every processing engine included). For Vercel
with managed PostgreSQL and S3-compatible storage, see
[`VERCEL_DEPLOYMENT.md`](VERCEL_DEPLOYMENT.md).

Status: the production files below are written and `docker compose ... config` validates
them. Automated tests check the contracts they rely on (only the proxy publishes ports, one
API worker, non-root user, no loopback API URL in the web image, rate-limit zones, the
start-up schema guard). **The images have not yet been built or run.** On the
development machine Docker Desktop is installed but its engine cannot start because the
Windows Subsystem for Linux is not installed (`wsl.exe --install`, administrator rights,
then a restart). Do a full trial deployment on a staging host before relying on them.

## What runs

```
Internet ──443──▶ Caddy (HTTPS, one public domain)
                    ├── /api/*, /health ──▶ api  (FastAPI, uvicorn, 1 worker)  ── /data volume
                    └── everything else ──▶ web  (Next.js, next start)
```

- One public origin. The browser calls the API on the same origin (relative URLs), so the
  `SameSite=Lax`, `HttpOnly`, `Secure` session cookie and the CSRF origin check work
  without cross-site configuration.
- Only Caddy publishes ports (80/443). The API, the web server and the database are not
  reachable from outside.
- All persistent state is in the `evidencex_data` volume: `/data/evidencex.db` (SQLite),
  `/data/storage` (evidence files, content-addressed) and `/data/models` (speech model).

Files: `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.prod.yml`,
`deploy/Caddyfile`, `deploy/.env.production.example`. `docker-compose.yml` (Postgres on
127.0.0.1) is for local development only.

## Why one API worker

Two features are single-process by design:

1. Evidence processing and analysis run as in-process background tasks.
2. The failed-sign-in throttle (`LOGIN_MAX_FAILURES` per e-mail within
   `LOGIN_LOCKOUT_MINUTES`) is kept in process memory. With several workers or
   replicas, each keeps its own count, so the effective limit multiplies. A restart also
   clears the counts.

The image therefore starts `uvicorn --workers 1`. Do not add workers or replicas without
first moving the throttle to shared storage (for example a database table) and the
background work to a queue.

## Proxy rate limits

Stock Caddy has no rate limiter, so `deploy/caddy/Dockerfile` builds Caddy with the
`github.com/mholt/caddy-ratelimit` module (Apache-2.0) using the official `caddy:2-builder`
image. `deploy/Caddyfile` limits per client address, before the request reaches the API:

| Zone | Request | Limit |
|---|---|---|
| `auth_login` | `POST /api/auth/login` | 10 per minute |
| `auth_register` | `POST /api/auth/register` | 5 per 10 minutes |

IPv6 clients are grouped per /64 network. Over the limit, Caddy answers `429`. This sits in front of the API's own per-e-mail
throttle. The proxy build downloads the module source at build time, so it needs network
access. If Caddy is not directly on the internet (for example behind a load balancer),
`{remote_host}` is the load balancer's address; configure `trusted_proxies` and key on the
client address instead.

## Start-up schema check

With `APP_ENV=production` (set in the API image) the API **refuses to start** when the
database has no Alembic revision or is not at the revision the code expects. The process
exits with `SchemaNotReadyError`, the container health check stays unhealthy, and the web
container (which waits for a healthy API) does not start. Run the migration first (below).
`alembic upgrade head` through `docker compose run` is not affected by the check. In
development the API still starts and answers 503 with the fix instead.

## Security headers

- Web (every page, `frontend/lib/csp.mjs`): a Content Security Policy with
  `default-src 'self'`, `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'self'`,
  `form-action 'self'`; `script-src` needs `'unsafe-inline'` for Next.js hydration
  scripts and gets `'unsafe-eval'` only in development. Plus `X-Frame-Options: DENY`,
  `nosniff`, `Referrer-Policy: no-referrer`, a restrictive `Permissions-Policy`, and no
  `X-Powered-By`. The policy is computed at **build time** from
  `NEXT_PUBLIC_API_BASE_URL`: empty (the image default) allows the same origin only.
- API: `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` on every
  response except the interactive docs (`/docs`, `/redoc`, `/openapi.json`), and
  `Cache-Control: no-store` on every `/api/*` response.
- Caddy adds HSTS and removes the `Server` header.

## First deployment

1. **Server:** Docker Engine with the compose plugin; DNS for your domain pointing at the
   server; ports 80 and 443 open.
2. **Settings:** `cp deploy/.env.production.example deploy/.env.production`, then set
   `EVIDENCEX_DOMAIN` and `CORS_ORIGINS=https://<domain>`. Keep `COOKIE_SECURE=true`.
   Never commit this file.
3. **Build:** `docker compose -f docker-compose.prod.yml build`
4. **Create the schema** (new, empty volume). This must come before the first start,
   because the API refuses to start on an unmigrated database:
   `docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head`
5. **Start:** `docker compose -f docker-compose.prod.yml up -d`
6. **Check:** `https://<domain>/health` must show `"status":"ok"` and
   `"schema": {..., "up_to_date": true}`. Also check that a page response carries the
   `Content-Security-Policy` header and that an 11th sign-in attempt within a minute gets
   `429`.
7. **Speech model** (only for audio and video): download it once into the volume with
   `docker compose -f docker-compose.prod.yml run --rm api python -m app.tools.fetch_whisper_model --size base`.
8. Register the team's accounts, then set `REGISTRATION_OPEN=false` and restart `api`.

## Moving an existing local database

1. Stop the local backend. Back up `backend/var/evidencex.db` and `backend/var/storage/`.
2. Copy both into the `evidencex_data` volume as `/data/evidencex.db` and `/data/storage/`
   (for example `docker cp` into a stopped `api` container).
3. Run `docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head` (a
   no-op if the copy is already at head), then start the stack.

## Backups

Back up the **database and the storage folder together**; claims reference stored files by
hash.

```sh
# consistent SQLite copy while the API runs
docker compose -f docker-compose.prod.yml exec api python -c "import sqlite3; s=sqlite3.connect('/data/evidencex.db'); d=sqlite3.connect('/data/backup-evidencex.db'); s.backup(d); d.close()"
# archive database copy + evidence storage
docker run --rm -v evidencex_evidencex_data:/data -v "$PWD":/out alpine \
  tar czf /out/evidencex-$(date +%Y%m%d-%H%M).tgz -C /data backup-evidencex.db storage
```

Verify each backup: `PRAGMA integrity_check` on the database copy must return `ok`.

## Restore

1. `docker compose -f docker-compose.prod.yml stop api`
2. Extract the archive into the volume, replacing `/data/evidencex.db` with the backed-up
   copy and `/data/storage` with the backed-up folder.
3. `docker compose -f docker-compose.prod.yml start api` and check `/health`.

## Upgrades and migrations

1. Back up (above). 2. `git pull` the new version. 3. Build:
`docker compose -f docker-compose.prod.yml build`. 4. Stop the API, run
`docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head`, start
everything. If you skip the migration, the new API refuses to start and the old data is
left untouched. 5. Check `/health`.

Never use `alembic stamp` to skip a migration.

## Rollback

- **Code only (no migration in the release):** check out the previous version and rebuild.
- **Release with a migration:** stop the stack, restore the pre-upgrade backup (database and
  storage), check out the previous version, rebuild, start. Prefer restoring a backup over
  `alembic downgrade`: downgrades drop the columns and tables the newer version added.

## Postgres

The application and migrations are written for SQLAlchemy and can use Postgres
(`DATABASE_URL=postgresql+psycopg://...`), but the test suite and all verification so far
ran on SQLite. Treat Postgres as untested until the suite has been run against it
(`TEST_DATABASE_URL`). Never publish the Postgres port.

## Licence obligations when you deploy

EvidenceX is AGPL-3.0, and PyMuPDF is used under the AGPL-3.0. Before people outside your
own machine use a deployment:
- Make sure the public repository contains **exactly the version you deploy** (push the
  commit first). The footer's "Source Code" and "License" links point to it, and
  generated PDFs name it in their metadata.
- If you deploy a modified version, change `frontend/lib/project.ts` and
  `backend/app/modules/analysis/pdf_notice.py` to point at the source of that version,
  and publish it.
- Do not strip the `producer` notice from generated PDFs.
- Do not push the built images to a public registry before the questions on PyAV's
  bundled GPL codecs and the base images are settled ("Needs legal review" in
  `THIRD_PARTY_LICENSES.md`). Building and running them on your own server does not
  distribute them.

---
EvidenceX · Copyright (C) 2026 Krina R. Chauhan · GNU AGPL-3.0 ([LICENSE](../LICENSE))
