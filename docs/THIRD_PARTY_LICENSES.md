# Licences: EvidenceX and third-party components

This page is an inventory. It is **not legal advice**.

## EvidenceX's own licence

EvidenceX (the code and documentation in this repository written for the project) is
Copyright (C) 2026 **Krina R. Chauhan** (see "Needs legal review") and is licensed under the **GNU Affero General
Public License, version 3** (AGPL-3.0). The full text is in the root [`LICENSE`](../LICENSE)
file, which is the unmodified text published by the Free Software Foundation at
<https://www.gnu.org/licenses/agpl-3.0.txt> (SHA-256
`0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0`, checked 2026-11-26).

The source code is published at <https://github.com/krinachauhan006/EvidenceX>. The
landing-page footer and the footer of every signed-in page link to it ("Source Code") and
to the licence ("License"). Every generated PDF names it in its `creator` metadata.

## Third-party components keep their own licences

Everything below is a separate work by other authors. Each one is used under **its own**
licence. The AGPL that covers EvidenceX does **not** replace, override or relicense any of
them, and the terms of each still apply to anyone who copies or redistributes it. The
licence families listed here are generally regarded as compatible with combining them
with AGPL-3.0 code: permissive (MIT, BSD, ISC, Apache-2.0, PSF, MIT-CMU, 0BSD, Zlib, CC0),
weak copyleft (LGPL-3.0, MPL-2.0), GPL-2.0-or-later (via GPL-3.0, which AGPL-3.0 section 13
allows combining with) and AGPL-3.0. That is a general reading, not a legal opinion for this
project. The items under "Needs legal review" below still need a qualified person to confirm
them.

Inventory of dependencies taken on 2026-11-25 from the installed backend environment
(`importlib.metadata`, Python 3.13 venv) and the frontend `node_modules`
(`npm ls --omit=dev --all`). Versions in the Docker images may differ slightly because
`pyproject.toml` uses minimum versions and the images install the newest match. Re-check
after dependency upgrades.

## PyMuPDF (© Artifex Software, Inc.; AGPL-3.0 or Artifex commercial)

PyMuPDF 2.1 (with MuPDF 1.28.6) does PDF text extraction, page rendering for OCR of
scanned pages, and the report and graph PDF output. Artifex offers it under the AGPL-3.0
or a commercial licence; EvidenceX uses it **under the AGPL-3.0**, which is why EvidenceX
itself is AGPL-3.0. Artifex's licensing page lists these obligations for the AGPL build
([pymupdf.io/licensing](https://pymupdf.io/licensing), checked 2026-11-26; paraphrased):

| Obligation | How EvidenceX meets it |
|---|---|
| Users of a networked deployment must receive the corresponding source under the AGPL | Source published on GitHub; footer links "Source Code" and "License". The published source must match what is deployed (see "Still to do") |
| Modified versions of the open-source code stay under the AGPL | PyMuPDF is used unmodified, as installed from PyPI |
| Keep the copyright and producer metadata in generated PDFs | Every report and graph PDF sets `producer` to `PyMuPDF <version> (MuPDF <version>), Copyright (C) Artifex Software, Inc., GNU AGPL-3.0` (`backend/app/modules/analysis/pdf_notice.py`, covered by a test). PyMuPDF writes no producer of its own, and EvidenceX previously overwrote it with "EvidenceX" |

`PDF_EXTRACTION_ENABLED=false` turns off PDF *extraction* only. Reports and graph PDFs
still use PyMuPDF, so this setting does not remove the dependency.

`pymupdf 2.1` also installs `pymupdf4llm 2.1` and `pymupdf-layout 2.1` (an empty
compatibility package), `networkx`, `psutil` and `tabulate`. EvidenceX imports `networkx`
directly (graph export) but does not declare it in `pyproject.toml`; it arrives through
PyMuPDF.

## Backend (Python), direct dependencies

| Package | Version | Licence |
|---|---|---|
| fastapi | 0.162.2 | MIT |
| uvicorn[standard] | 0.54.0 | BSD-3-Clause |
| SQLAlchemy | 2.1.8 | MIT |
| pydantic / pydantic-core | 2.14.3 / 2.50.4 | MIT |
| pydantic-settings | 2.16.2 | MIT |
| alembic | 1.20.1 | MIT |
| psycopg / psycopg-binary | 3.3.8 | **LGPL-3.0-only** |
| python-multipart | 0.0.33 | Apache-2.0 |
| **pymupdf** | 2.1 | **AGPL-3.0 or Artifex commercial** |
| pillow | 13.0.0 | MIT-CMU |
| pytesseract | 0.3.13 | Apache-2.0 |
| openpyxl | 3.1.5 | MIT |
| defusedxml | 0.7.1 | PSF-2.0 |
| faster-whisper (optional `audio`) | 1.2.1 | MIT |
| pytest, httpx, ruff (dev only) | 9.2.0, 0.28.1, 0.17.4 | MIT, BSD-3-Clause, MIT |

## Backend, important transitive dependencies

| Package | Version | Licence | Note |
|---|---|---|---|
| starlette | 1.10.0 | BSD-3-Clause | via FastAPI |
| anyio, h11, httptools, watchfiles | 4.16.0, 0.16.0, 0.9.0, 1.3.0 | MIT | |
| websockets, click, python-dotenv | 17.4, 8.5.1, 1.2.4 | BSD-3-Clause | |
| networkx | 3.7 | BSD-3-Clause | via PyMuPDF, imported directly |
| psutil | 7.2.2 | BSD-3-Clause | via PyMuPDF |
| tabulate | 0.10.0 | MIT | via PyMuPDF |
| Mako / MarkupSafe | 1.4.3 / 3.0.4 | MIT / BSD-3-Clause | via Alembic |
| et_xmlfile | 2.0.0 | MIT | via openpyxl |
| ctranslate2 | 4.9.0 | MIT | via faster-whisper |
| onnxruntime | 1.32.0 | MIT | via faster-whisper (voice activity filter) |
| av (PyAV) | 19.0.2 | BSD-3-Clause (the binding) | **The wheel bundles native FFmpeg libraries plus `libx264` and `libx265`, which are GPL-licensed.** The Windows wheel inspected here contains `avcodec`, `avformat`, `avfilter`, `swscale`, `libx264`, `libx265`, `libvpx`, `libdav1d`, `libSvtAv1Enc`, `libopus`, `libwebp`, `libiconv` and the MinGW runtime, and ships **no licence text** for any of them. The Linux wheel used in the Docker image was not inspected. See "Needs legal review" |
| tokenizers, huggingface_hub, hf-xet | 0.23.3, 2.4.0, 1.8.0 | Apache-2.0 | via faster-whisper |
| numpy | 2.5.4 | BSD-3-Clause (+ bundled 0BSD/MIT/Zlib/CC0) | |
| protobuf, flatbuffers | 7.36.2, 25.12.19 | BSD-3-Clause, Apache-2.0 | via onnxruntime |
| certifi | 2026.10.23 | **MPL-2.0** | Unmodified use is fine; changes to its files would have to be shared |
| tqdm | 4.70.1 | MPL-2.0 AND MIT | Same note as certifi |
| idna, fsspec | 3.20, 2026.9.0 | BSD-3-Clause | |
| filelock, typing-inspection, truststore | 4.2.10, 0.4.5, 0.10.5 | MIT | |
| typing_extensions | 4.16.0 | PSF-2.0 | |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | |

## Frontend (npm), shipped to the browser or the web server

| Package | Version | Licence |
|---|---|---|
| next | 14.2.35 | MIT |
| react / react-dom | 18.3.1 | MIT |
| lucide-react (icons) | 0.454.0 | ISC |
| clsx | 2.1.1 | MIT |
| styled-jsx, @next/env, scheduler, loose-envify, js-tokens, nanoid, client-only, busboy, streamsearch | various | MIT |
| @swc/helpers, @swc/counter | 0.5.5, 0.1.3 | Apache-2.0 |
| postcss (Next internal) / source-map-js / picocolors / graceful-fs | 8.4.31 / 1.2.2 / 1.1.1 / 4.2.11 | MIT / BSD-3-Clause / ISC / ISC |
| tslib | 2.9.1 | 0BSD |
| caniuse-lite | 1.0.30001823 | **CC-BY-4.0** (browser-support data used by the build; attribution: "Can I use", Alexis Deveria) |
| @next/swc-win32-x64-msvc (build machine only) | 14.2.33 | MIT |

Build-time only (not shipped): typescript 5.6.3 (Apache-2.0), tailwindcss 3.4.14, postcss
8.4.47, autoprefixer 10.4.20, eslint 8.57.1, eslint-config-next 14.2.35, @types/* (all MIT).

## System software and container images

| Component | Licence | Where |
|---|---|---|
| Tesseract OCR + `eng` traineddata (Debian `tesseract-ocr`) | Apache-2.0 | API image |
| `python:3.12-slim` (Debian bookworm base, CPython) | PSF-2.0; Debian packages under their own licences (GPL/LGPL/BSD etc.) | API image |
| `node:20-alpine` (Node.js, Alpine/musl, BusyBox) | MIT; Alpine packages under their own licences (BusyBox is GPL-2.0) | web image |
| Caddy 2 | Apache-2.0 | proxy image |
| caddy-ratelimit (`github.com/mholt/caddy-ratelimit`) | Apache-2.0 | proxy image |
| Whisper speech model (faster-whisper conversion of OpenAI Whisper) | MIT | downloaded on request into `/data/models`; not in the repository |

Base images contain GPL-licensed system packages. Redistributing the built images
(for example pushing them to a public registry) means also making those packages' sources
available, as the Debian and Alpine projects do; running them yourself does not.

## Landing-page images

The only image file shipped is `wall-*` (`frontend/public/images/landing/wall-768.webp`,
`wall-1280.webp`, `wall-1920.webp`). The project owner generated it with Google Gemini and
declared it cleared; that was not independently verified here. Every other landing visual
is original CSS (`app/globals.css`, `.evx-art-*`) and loads no files.

Six photographs with **unverified rights** were removed from the site on 2026-11-26 and
are no longer shipped or referenced: `desk`, `forensic`, `notebook`, `corkboard` (all
downloaded from third-party web pages) and `fingerprints`, `lampboard` (received over
WhatsApp, origin unknown). Details: `frontend/LANDING_IMAGES.md`. A test fails if any
image other than `wall-*` is added to `public/images/landing/`.

Images are not part of the AGPL-licensed work unless their rights holder licenses them;
the `LICENSE` grants nothing for third-party images.

## Needs legal review

These are questions for a qualified person, not technical defects. They are listed so
they are not mistaken for settled points.

1. **Copyright holder.** The notices say `Krina R. Chauhan`. The only
   Git author and committer is `krinachauhan006 <krinaa006@gmail.com>`, which is an
   account name, not a confirmed legal owner. Confirm who holds the copyright: an
   individual, several contributors, or an organisation (for example under hackathon
   rules or an employment or study agreement).
2. **AI-assisted code.** Much of the code was written with an AI assistant (Kiro).
   Whether and how such output is protected by copyright, and therefore who can license
   it, depends on jurisdiction.
3. **"AGPL-3.0 only" or "or any later version".** The notices currently say version 3 only.
4. **PyAV / FFmpeg / x264 / x265.** The PyAV wheel bundles GPL-licensed codec libraries
   without their licence texts. Running EvidenceX on your own server does not convey
   them. **Publishing the Docker images** would. You would then have to provide the GPL
   and LGPL licence texts and the corresponding source (or a written offer) for those
   libraries. Possible routes: do not publish images; or build the images with FFmpeg
   from the Debian packages, which ship licence files and have a published source; or
   include the pyav-ffmpeg build sources and notices. Also confirm which build the Linux
   wheel uses.
5. **psycopg (LGPL-3.0).** It is used only for Postgres and is imported unmodified, which
   generally satisfies the LGPL. If images are published, include its licence text.
6. **MPL-2.0 (certifi, tqdm) and CC-BY-4.0 (caniuse-lite).** These are file-level
   copyleft and attribution obligations. They are met by unmodified use plus the
   attribution on this page.
7. **Gemini.** This is service terms rather than a licence. Before enabling AI on a case,
   check that Google's terms allow sending that evidence, and the terms that apply to
   model output. The `wall` artwork was also generated with Gemini; its usable rights
   depend on the owner's account terms.
8. **Base images (Debian, Alpine).** These contain GPL system packages. Publishing images
   brings their source-offer obligations; running them yourself does not.

## Still to do
- **Publish the deployed source.** The public repository holds only the Phase 1
  baseline (commit `cf87106`). The code that would be deployed, including `LICENSE`, is
  uncommitted, so the "License" link returns 404 until it is pushed. Push, and tag, the
  exact version you deploy before the site goes live.
- Confirm the copyright holder and replace the placeholder (Needs legal review, item 1).

---
EvidenceX · Copyright (C) 2026 Krina R. Chauhan · GNU AGPL-3.0
([LICENSE](../LICENSE)). The components listed on this page are covered by their own licences.
