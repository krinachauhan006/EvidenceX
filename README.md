# EvidenceX

*One Case. Multiple Evidence Formats. Connected Findings.*

**Multimodal evidence intelligence and investigation workspace.** EvidenceX brings PDFs,
images, audio, video, e-mail (`.eml`) and spreadsheets (CSV/XLSX) into one case. Every
extracted claim links to its exact source location (page and box, pixel region,
timestamp, frame, cell or e-mail part). Possible inconsistencies are surfaced for people to
review.

Built for the **Kiroween 2026** hackathon (Frankenstein category) with the Kiro AI IDE.

> EvidenceX is an analytical aid. It does **not** determine guilt or innocence, detect
> lies or deception, or authenticate evidence. Confidence values are heuristic
> self-assessments that explain how a rule matched. They are not probabilities that
> something is true.

## What it does

- **Intake and validation.** The real file type is read from its bytes (magic numbers),
  not the file name. Uploads have per-type size limits, are stored under their SHA-256
  outside any web-served folder, and are never executed.
- **Extraction with provenance.** The extractors are:
  - PDF text blocks, with OCR fallback for scanned pages
  - image OCR, with orientation and deskew
  - local speech recognition (faster-whisper)
  - sampled video frames, with frame OCR and a soundtrack transcript
  - e-mail headers and parts
  - table rows and cells

  Each segment keeps its physical locator.
- **Claims.** Statements with a time, date, quantity, identifier or place become claims
  that quote their source and stay unverified until reviewed. Claim extraction is
  rule-based by default. AI (Gemini) runs only when a key is configured **and** the case
  owner allows it, and its output is schema-validated.
- **Entities and events.** Identical identifiers link records. Similar ones are offered as
  tiered candidates and are never merged automatically. Claims that may describe one
  occurrence are proposed as events, which a reviewer confirms.
- **Possible inconsistencies.** Accounts are compared within a confirmed event. Each
  finding lists both sources, the reason they may differ, benign alternative
  explanations and a heuristic detection confidence. Dates and times keep the precision
  the source gives.
- **Workspace.** Case dashboard, evidence viewers (PDF, image, audio, video, e-mail,
  table), claims, entities, events, timeline, contradictions, knowledge graph, search
  and "ask" (answers from source passages, with citations), reports, audit and settings.
- **People decide.** Owner, editor, reviewer and viewer roles are checked by the server on
  every request. Every decision is recorded in a SHA-256-chained, tamper-evident audit
  trail. Reports are versioned PDFs with a content hash. The knowledge graph exports as
  JSON or GraphML.

## Supported formats

The type is detected from the file's content. Each format has an extractor and
integration tests.

| Format | Extensions | Source locator kept for every segment |
|---|---|---|
| PDF | .pdf | page and bounding box (embedded text; OCR for scanned pages) |
| Images | .png .jpg .jpeg .webp | pixel region (OCR, with orientation and deskew) |
| Audio | .wav .mp3 .m4a | start and end time, word timing (local faster-whisper) |
| Video | .mp4 .mov .webm | frame time and text region; soundtrack as audio |
| E-mail | .eml | header name or message part; attachments listed, never opened |
| Tables | .csv .xlsx | row and column; sheet and cell (formulas shown, never run) |

OCR needs Tesseract installed. Audio and video speech recognition needs the `audio`
extra and a downloaded Whisper model. Without them those items fail with a clear
"dependency missing" status, and other files are unaffected.

## AI status

| Function | Status |
|---|---|
| Claim extraction with Gemini (`CLAIM_EXTRACTOR=gemini` or `hybrid`) | Implemented, tested with a mocked model; **not yet tested against the live Gemini API** |
| "Ask" answers drafted by Gemini | Implemented, mocked tests only; **not live-tested** |
| AI-drafted report summary | Implemented, mocked tests only; **not live-tested** |
| Fallback without AI | Rule-based claims, source-passage answers for "Ask", and a rule-based report summary. This is the default and is tested. |
| Entity resolution, event proposals, contradiction detection | Rule-based only (no AI) |

AI runs only when `GEMINI_API_KEY` is set **and** the case owner enables AI for that case.
AI output is schema-validated and labelled as AI in the UI and in reports.

## Documentation

[Architecture](docs/ARCHITECTURE.md) · [Deployment, backup and restore](docs/DEPLOYMENT.md)
· [Security and privacy](docs/SECURITY.md) · [Third-party licences](docs/THIRD_PARTY_LICENSES.md)
· [Demo guide](docs/DEMO.md) · [Licence (GNU AGPL-3.0)](LICENSE) · API: `/docs`
(OpenAPI) on the running backend.

## Architecture

A modular monolith with two deployables, which talk over REST:

| Part | Stack |
|---|---|
| `backend/` | FastAPI, SQLAlchemy 2, Alembic, Pydantic v2 (Python ≥ 3.11). Feature modules under `app/modules/<feature>/` (router → service → repository). |
| `frontend/` | Next.js 14 App Router, TypeScript (strict), Tailwind CSS, lucide-react. |

Project conventions, invariants and the specifications used to build EvidenceX with Kiro are
in [`.kiro/steering/`](.kiro/steering) and [`.kiro/specs/`](.kiro/specs).

## Running locally

Prerequisites:
- Python 3.11 or newer
- Node.js 22.6 or newer (the frontend unit tests use `--experimental-strip-types`)
- Optional: [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) for images and
  scanned PDFs
- Optional: FFmpeg-capable PyAV (installed with the `audio` extra) for audio and video

### 1. Backend (http://localhost:8000)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"           # add ,audio for speech/video: pip install -e ".[dev,audio]"
copy .env.example .env            # macOS/Linux: cp .env.example .env ; then edit
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

If the sign-in page says the database needs an update, the database is older than the
code (for example still at `0006`, before accounts existed). Back up the database
file, then run `alembic upgrade head` in `backend/`. `GET /health` shows the database
and expected revisions under `schema`.

Without `DATABASE_URL`, the backend uses a local SQLite file (`backend/var/evidencex.db`).
`docker compose up -d` starts a local Postgres that matches the URL in `.env.example`. The
Whisper speech model is never downloaded automatically. To fetch it once, run:
`python -m app.tools.fetch_whisper_model --size base`.

### 2. Frontend (http://localhost:3000)

```powershell
cd frontend
npm ci
copy .env.local.example .env.local   # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm run dev                           # production: npm run build ; npm run start
```

Open http://localhost:3000, choose **Start an Investigation**, create an account and
start a case. The first account receives no existing data. Cases created before sign-in
existed go only to the account named in `LEGACY_CASES_OWNER_EMAIL`, or are assigned with
`python -m app.cli claim-legacy-cases EMAIL --dry-run` (drop `--dry-run` to apply).

### Settings

All settings are environment variables; see `backend/.env.example`. Secrets are never
committed. The settings most relevant to a demo:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | SQLite in `./var` | Database connection |
| `STORAGE_ROOT` | `./var/storage` | Content-addressed evidence storage |
| `CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Allowed frontend origins (comma-separated) |
| `COOKIE_SECURE` | `false` | Set `true` when served over HTTPS |
| `REGISTRATION_OPEN` | `true` | Allow new accounts |
| `SESSION_DAYS` | `7` | Session lifetime |
| `LOGIN_MAX_FAILURES` / `LOGIN_LOCKOUT_MINUTES` | `8` / `15` | Failed sign-in throttle (in memory, per process) |
| `LEGACY_CASES_OWNER_EMAIL` | empty | Account that receives cases created before sign-in existed |
| `CLAIM_EXTRACTOR` / `GEMINI_API_KEY` | `rule_based` / empty | Optional AI claim extraction (needs per-case consent) |

Passwords need at least **8** characters (Unicode code points), at most 256, and no
leading or trailing spaces. They are hashed with scrypt. Sessions are HttpOnly,
SameSite=Lax cookies, and only a hash of each session token is stored. Writes from
untrusted origins are refused (CSRF check).

## Tests

```powershell
cd backend ; .venv\Scripts\python.exe -m pytest -q          # unit + integration (AI always mocked)
cd frontend ; npm run typecheck ; npm run lint
cd frontend ; node --experimental-strip-types --no-warnings --test tests/*.test.mjs
```

## A first look for judges

1. Read the landing page. The hero shows a fictional "missing shipment" case: six
   evidence files become cited claims and one suggested event, ending in a possible
   inconsistency that awaits human review. Hover, focus or tap a file to trace its path.
2. Create an account, start a case and upload a PDF, a photo or scan, an audio file, a
   short video, an `.eml` file and a CSV/XLSX.
3. Run the analysis. Open a claim to jump to its exact source location. Confirm a proposed
   event under **Events**, then review the possible inconsistency, with its alternative
   explanations, under **Contradictions**.
4. Generate a report (PDF), export the graph (JSON/GraphML) and check **Audit** for the
   chained record of every decision.

## What has been tested, and what has not

| Area | Status |
|---|---|
| Backend API, extractors, auth, case isolation, reports, audit chain | Automated tests (pytest, AI always mocked) |
| Frontend helpers, CSP builder | Node unit tests; typecheck and lint |
| Sign-in, workspace, landing page in a real browser | Scripted Chromium runs against a local production build |
| Gemini (claims, "Ask" drafts, report summary) | **Mocked only, not live-tested.** Needs `GEMINI_API_KEY`, network access and per-case consent |
| OCR | Needs Tesseract installed on the host (included in the API Docker image) |
| Audio and video speech | Needs the `audio` extra and a Whisper model downloaded once (never automatic) |
| Docker images and the production stack (Caddy HTTPS, rate limits) | **Written but not built or run yet.** See [DEPLOYMENT](docs/DEPLOYMENT.md) |
| Postgres | Supported by the code, but all tests ran on SQLite |

## Limitations

- Rule-based extraction finds explicit times, dates, quantities, identifiers and places;
  it does not understand free narrative. AI extraction needs a Gemini key and per-case
  consent.
- OCR and speech recognition quality depends on the input. Low-confidence output is kept
  and marked, never upgraded.
- The failed-login throttle is in memory: it resets on restart and is per process.
- Background processing runs in-process (FastAPI background tasks); there is no task
  queue.

## Licence

EvidenceX is licensed under the **GNU Affero General Public License, version 3**
(AGPL-3.0). The full text is in [`LICENSE`](LICENSE).

```
EvidenceX — multimodal evidence intelligence and investigation workspace
Copyright (C) 2026 Krina R. Chauhan

This program is free software: you can redistribute it and/or modify it under the
terms of the GNU Affero General Public License, version 3, as published by the Free
Software Foundation.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License along with
this program. If not, see <https://www.gnu.org/licenses/>.
```

Because of the AGPL, anyone who runs a **modified** EvidenceX for other people over a
network must offer those users the source code of that modified version. The footer of
the landing page and of every signed-in page links to the source code and this licence.
If you deploy a fork, change
`frontend/lib/project.ts` and `backend/app/modules/analysis/pdf_notice.py` to point at
your fork.

The AGPL covers EvidenceX's own code. Third-party libraries, tools and images keep their
own licences, which the AGPL does not replace. See
[Third-party licences](docs/THIRD_PARTY_LICENSES.md). In particular:
- PDF extraction and the PDF reports use PyMuPDF (© Artifex Software, Inc.), used here
  under the AGPL-3.0. Generated PDFs keep PyMuPDF's producer and copyright notice in
  their metadata. `PDF_EXTRACTION_ENABLED=false` turns off PDF extraction only; reports
  still use PyMuPDF.
- PyAV (audio and video) ships GPL-licensed codec libraries (`libx264`, `libx265`) in its
  wheel. This matters if you publish Docker images; see "Needs legal review" in
  [Third-party licences](docs/THIRD_PARTY_LICENSES.md).
- The landing page ships one image, the owner-generated `wall` artwork. Six photographs
  with unverified rights were removed and replaced by CSS artwork. See
  [`frontend/LANDING_IMAGES.md`](frontend/LANDING_IMAGES.md).

The copyright holder named above is a placeholder that must be confirmed before release.
