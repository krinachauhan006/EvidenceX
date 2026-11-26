# Security and privacy notes

These notes describe how EvidenceX behaves today and what has been checked. They come from
code review and the automated test suite. They are not a penetration test.

## Accounts and sessions
- Passwords: 8–256 characters (Unicode code points), no leading or trailing spaces, the
  same rule in the form and on the server. Hashed with scrypt (n=2^14, r=8, p=1, 16-byte
  random salt). Unknown e-mail addresses take the same time as wrong passwords, and both
  get the same message.
- Sessions: 32 random bytes in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` when
  `COOKIE_SECURE=true`). Only SHA-256(token) is stored. Sign-out revokes the token on the
  server, so a copied cookie stops working. Sessions expire after `SESSION_DAYS`.
- Failed sign-ins are throttled per e-mail address (`LOGIN_MAX_FAILURES` within
  `LOGIN_LOCKOUT_MINUTES`). **Limitation:** the counter is in process memory. It resets on
  restart and is not shared between processes, so production runs a single API worker
  (see `DEPLOYMENT.md`). In the Docker stack, Caddy also limits sign-in (10 per minute)
  and registration (5 per 10 minutes) per client address (`deploy/Caddyfile`).

## Authorisation
- Every case-scoped route checks membership on the server: owner > editor > reviewer >
  viewer. Non-members get 404, so they cannot tell a case exists.
- Only owners manage members, consent and deletion. A case always keeps at least one owner.
  Nobody can raise their own role.
- Cases created before accounts existed belong to nobody until an operator assigns them
  (`LEGACY_CASES_OWNER_EMAIL` or `python -m app.cli claim-legacy-cases EMAIL`).

## Requests
- CSRF: state-changing requests are refused when `Origin` is not in `CORS_ORIGINS` (or
  `Sec-Fetch-Site` is `cross-site`), in addition to `SameSite=Lax`.
- CORS: explicit allow-list with credentials; no wildcard.
- Response headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`; Caddy adds HSTS.
- Content Security Policy. Web pages: `default-src 'self'`, `frame-ancestors 'none'`,
  `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`. **Limitation:**
  `script-src` includes `'unsafe-inline'` because Next.js 14 injects inline hydration
  scripts and no nonce middleware is used; `'unsafe-eval'` is added in development only.
  API responses: `default-src 'none'; frame-ancestors 'none'` (except the interactive
  docs) and `Cache-Control: no-store` on `/api/*`, so case data is not kept by caches.
- In production the API refuses to start on a database with pending migrations.
- Validation errors return only `type`, `loc` and `msg`; submitted values (passwords) are
  never echoed. A database that is older than the code answers 503 with the fix, without
  SQL or parameters.

## Uploads and evidence
- The real file type is read from its content (magic bytes), not the name or MIME type.
  Size and type limits are checked before processing; XLSX archives are checked for
  entry counts, sizes and compression ratio (zip-bomb protection).
- Files are stored under their SHA-256 outside any web-served folder and are never
  executed. Storage paths come only from the hash, never from the uploaded name.
- Extraction runs in a separate subprocess with a time limit (`PROCESSING_ISOLATION`),
  so one bad file fails only itself.

## AI and prompt injection
- External AI (Gemini) is used only when `GEMINI_API_KEY` is set **and** the case owner
  turns on AI for that case (an audited decision). Otherwise no evidence text leaves the
  server.
- Evidence text is placed inside delimited blocks that the prompt declares untrusted data.
  Model output is validated against a schema and quotes are re-checked against the source.
  One repair attempt is made, then the item fails; nothing is invented.

## Audit
- Every review decision is attributed to the signed-in account and chained by SHA-256.
  Altering a past record breaks the chain, and the Audit page and reports show this. The
  latest hash is not anchored outside the database, so someone with full database write
  access could rebuild the chain (documented limitation).

## Secrets and data
- Secrets come from the environment only. `.env` files, databases, backups, evidence
  storage, models and build output are excluded from Git (`.gitignore`).
- Logs never contain passwords, tokens or file bytes.

---
EvidenceX · Copyright (C) 2026 Krina R. Chauhan · GNU AGPL-3.0 ([LICENSE](../LICENSE))
