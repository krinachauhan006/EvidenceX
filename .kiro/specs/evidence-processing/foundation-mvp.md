# Foundation MVP — status, operation and verification

This document describes what EvidenceX does today, how to run and test it, and what a
person still has to verify. It is kept in step with the code; if they disagree, the code
and its tests are right and this file needs a fix.

EvidenceX does **not** judge guilt or innocence, detect lies, or authenticate evidence.
Extracted text is data. Confidence values are the extraction engine's own score and say
nothing about factual accuracy.

## 1. What works

### Cases
Create, open, edit (title, description), archive, restore (Unarchive), delete. Deleting a
case removes its evidence rows, extraction runs, segments and any blob no other evidence
still uses.

### Evidence ingestion
Upload validates extension AND content, enforces the size limit before any processing,
hashes with SHA-256, and stores content-addressed (the file name never builds a path).

| Format | Upload check | Extractor | Result |
|---|---|---|---|
| CSV | text-like, no binary, control-character ratio | stdlib `csv` | header + row segments with row/line/column locators |
| XLSX | ZIP signature, shared ZIP guard (limits below), OLE rejected | openpyxl read-only + defusedxml | header + row segments, sheet/row/range locators, cell coordinates |
| EML | real RFC 5322 header block with an identity header | stdlib `email` | header, text body, HTML-as-text body, attachment segments |
| PDF | `%PDF-` signature | PyMuPDF (AGPL, see section 5) | text blocks with page + box; OCR lines for scanned pages |
| PNG / JPG / JPEG / WebP | signature | Pillow + Tesseract | OCR lines with pixel boxes, EXIF subset |
| WAV / MP3 / M4A | signature | faster-whisper | timestamped machine transcript (needs the model, section 4) |

Not supported: video (deferred by the architecture), legacy `.xls`/`.doc`, ZIP archives
as evidence, attachment contents inside emails (listed, never opened).

### Processing lifecycle
`pending -> processing -> completed | failed`. Every attempt that reaches a result is
kept as an immutable run with its own segments. One completed run is `current`. A forced
re-run adds a run; a failed attempt records a failed run and leaves the previous current
run readable. Items fail independently. Retry is allowed only for failed items.

### Frontend
Case list and detail, upload with progress and validation errors, evidence rows with
status, Process / Retry / Re-process, process-all-pending with progress, extraction
viewer with run history, pagination, source references, warnings, metadata, download,
delete. XLSX cells show their coordinate, and formulas show their text and "(no cached
value)" when the file has none.

## 2. Limits (all configurable, see `backend/.env.example`)

| Limit | Default |
|---|---|
| Upload size | 25 MB |
| ZIP entries / total expanded / per entry / shared strings / ratio | 2,000 / 100 MB / 50 MB / 20 MB / 100:1 |
| Tabular rows, cell length, extracted characters | 50,000 / 32,768 / 5,000,000 |
| PDF pages, image pixels | 500 / 50,000,000 |
| OCR time per image | 120 s |
| Audio length (`MAX_AUDIO_SECONDS`) | 1,200 s (20 min), checked while decoding, before the model loads |
| Audio processing time (`AUDIO_TIMEOUT_SECONDS`) | 1,800 s, checked between ~30 s transcript windows |

The audio defaults suit a machine with about 7.5 GB of RAM: 20 minutes decodes to about
77 MB of samples, and `small` (about 0.7–0.9× real time on the test CPU) finishes a
20-minute file well inside 30 minutes. An over-length file fails as `limit_exceeded`; a
slow one fails as `timeout`. Neither records a partial transcript, and earlier runs stay
current. The timeout is cooperative: one ~30 s window in progress is not interrupted.

### Audio transcripts
- Every transcript segment is labelled **AI-generated transcription** and **Unreviewed**.
  The stored text is the model's output and is never edited; the API reports
  `review_status: "unreviewed"`. Human review is not built. When it is, reviewed text
  must go in its own table keyed by segment id, never into the segment.
- Word detail shows each word with its time and engine-reported probability. Words
  below `WHISPER_LOW_WORD_PROBABILITY` are underlined and listed. This flag is a hint:
  in benchmarking it missed a wrong identifier digit at probability 0.502.
- "Play this segment" plays the original upload from the segment start and stops at its
  end (up to ~0.25 s late). The file is fetched through the case-scoped download
  endpoint on first use.
- Speech-model errors: `model_unavailable` (not on disk: download it), `model_invalid`
  (files damaged or incomplete), `resource_exhausted` (not enough memory),
  `model_init_failed` (anything else while starting). Only the first two suggest
  downloading. `WHISPER_MODEL_DIR`, when relative, is resolved from `backend/`.

The ratio rule applies to entries of 64 KiB or more, and to the whole package above 1 MiB.
Exceeding a limit during extraction fails the item with `limit_exceeded`, or stops early and
marks the run `partial` where partial text is meaningful.

## 3. Extraction behavior and warnings

Outcomes: `ok`, `partial`, `needs_ocr`, `empty`. `needs_ocr` and `empty` are never shown
as plain success.

| Warning code | Meaning |
|---|---|
| `encoding_assumed`, `delimiter_assumed`, `ragged_rows`, `header_keys_generated`, `cell_truncated`, `row_limit_reached`, `char_limit_reached`, `no_data_rows`, `empty_file` | CSV / tabular handling |
| `hidden_sheet`, `empty_sheet`, `chartsheet_skipped`, `contains_macro_binary`, `formulas_not_evaluated`, `no_cached_value` | XLSX |
| `duplicate_header`, `date_unparseable`, `charset_fallback`, `decoding_replacements`, `mime_defect`, `html_hidden_content`, `body_not_readable`, `no_body` | EML |
| `encrypted_no_user_password`, `pdf_repaired`, `page_limit_reached`, `pages_need_ocr`, `ocr_applied`, `ocr_unavailable`, `ocr_failed`, `page_too_large_for_ocr`, `no_text_found` | PDF |
| `no_text_detected`, `low_confidence`, `gps_metadata_present` | images and OCR |
| `no_speech_detected` | audio |

Error codes on failed runs: `corrupt_file`, `password_required`, `unsupported_content`,
`dependency_missing`, `model_unavailable`, `limit_exceeded`, `timeout`, `storage_missing`,
`internal_error`. Messages never contain file content or paths.

Fidelity rules: nothing is invented or corrected. Dates stay as written, with their
precision and whether a timezone was stated. XLSX formulas are kept as text, never
calculated. HTML is converted to text without rendering; hidden-styled text is kept
separately and flagged. Email attachments are described (name, type, size, SHA-256) and
never opened. The XLSX serial number is recomputed from the parsed value (the read-only
reader does not expose the raw one) and is labeled `serial_source: derived`.

Documented extraction limits: XLSX merged cells, comments, charts and images are not
extracted. OCR does not rebuild tables. Image boxes are measured after EXIF orientation.

## 4. Setup, run, test

Python 3.13 venv in `backend/.venv`; Node 22 for the frontend. No database migration is
needed for this stage beyond `0004` (no schema changes were made after it).

```powershell
# backend (from D:\Projects\EvidenceX\backend)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
# frontend (from D:\Projects\EvidenceX\frontend)
npm.cmd run dev
```

Tesseract is found on PATH, via `TESSERACT_CMD`, or in `C:\Program Files\Tesseract-OCR`.
The speech model is never downloaded by the application. To enable audio, once:

```powershell
.\.venv\Scripts\python.exe -m app.tools.fetch_whisper_model --size base
```

Tests (isolated: in-memory database and a temp blob store; they never touch `var\`):

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests
# frontend
npm.cmd run typecheck ; npm.cmd run lint ; npm.cmd run build
```
Do not run `npm run build` while `next dev` is serving from the same folder: both use
`.next`. Stop the dev server first.

Sample inputs for manual checks: `python -m tests.fixtures.generate_manual_samples`
writes synthetic files and a README of expected results to `sample-evidence\`.

## 5. Licensing and dependencies

| Package | License | Note |
|---|---|---|
| pymupdf 2.1 | AGPL-3.0 or Artifex commercial | Used unmodified as a local library. If EvidenceX is ever offered to other people as a network service, the AGPL terms (or a commercial license) must be settled first. `PDF_EXTRACTION_ENABLED=false` turns PDF processing off. Its helper packages `pymupdf4llm` and `pymupdf-layout` carry no license text in their metadata and are not imported by the code. |
| pillow | MIT-CMU | |
| pytesseract (Apache-2.0), Tesseract (Apache-2.0) | | the binary is installed separately |
| openpyxl, et-xmlfile | MIT | |
| defusedxml | PSF | required for XLSX safety |
| faster-whisper, ctranslate2 | MIT | optional `audio` extra |

No dependency was added in the Foundation MVP work.

## 6. Known limitations and open items

- **Audio is untested with a real model.** The code path, failure behavior and tests with a
  fake transcriber exist. No model is installed, so no real transcription has run.
- **No wall-clock timeout for extraction** other than OCR. A hostile file can occupy a
  worker thread until limits stop it. A subprocess executor (Phase 7) is not built.
- Extraction runs in the web process. Native parsers (MuPDF, Pillow, PyAV, Tesseract)
  read untrusted files in-process.
- XLSX dates: the serial is derived, not raw. 1900-date-system leap-year quirk applies.
- Video, `.xls`, and nested email contents are out of scope.
- The editable-install finder in the D: venv still points at the C: `app` folder
  (not changed; a separate maintenance task).
- The advanced intelligence features (claims, contradictions, graph, summaries) are
  deliberately not built.

## 7. Manual verification checklist

Prepare once: restart the backend so it loads the new code (the running one was started
before these changes), generate samples if the folder is missing, open
`http://localhost:3000/cases`. Use a NEW case named `MVP check` and delete it at the end.

| # | Steps | Expected |
|---|---|---|
| 1 | New case, open it, Edit the title, Archive, filter "archived", open it, Unarchive, filter "open" | Each step works; status badge changes |
| 2 | Upload `sample-evidence\ledger.csv`, `register.xlsx`, `message.eml`, `report.pdf` | Progress bar, four rows, all Pending, correct type icons |
| 3 | Click "Process all pending" | Statuses move to Completed; counts update |
| 4 | Open `register.xlsx` > View extraction | Sheets Payments, Approvals, Internal notes; hidden-sheet warning; C4 shows `=SUM(C2:C3)` and "(no cached value)"; D2 shows 2026-10-12 as a date; source reference like `Sheet "Payments" · C4` |
| 5 | Open `message.eml` | Header rows (From, To, Cc, Subject, Date, Message-ID), text body, HTML body without tags, two attachments listed with size |
| 6 | Open `report.pdf` | Text blocks with "Page 1/2/3" and a box in points |
| 7 | Re-process `register.xlsx` and confirm | Run history shows run 2 current; open run 1 and see its original segments |
| 8 | Upload `scanned.pdf`, `invoice-scan.png`, `blank.png`, `password-protected.pdf`, `broken-workbook.xlsx`; Process all | scanned.pdf and invoice-scan.png: OCR lines with engine-reported confidence (if Tesseract is installed); blank.png: "No extractable content"; password-protected.pdf: Failed "Password required"; broken-workbook.xlsx: Failed "Corrupt or unreadable file"; the others unaffected |
| 9 | Click Retry on the failed item | It runs again and fails again with the same reason; attempts increase |
| 10 | Upload `tone.wav`, Process | Failed "Model unavailable" with the download command (expected until the model is downloaded) |
| 11 | Try each file in `sample-evidence\should-be-rejected` | Each upload shows an error and no row appears |
| 12 | Download `ledger.csv` then Delete it | File downloads; row disappears; no error |
| 13 | Failure and recovery (optional, in this case only): rename the blob of one processed item in `backend\var\storage` (only the one belonging to the new case), Re-process, observe Failed + "earlier results still available", rename it back, Retry | Failed then Completed; earlier run still readable |
| 14 | Delete the case | Case gone; other cases untouched |

API spot checks (`http://localhost:8000/docs`): `GET /api/cases/{id}/processing`,
`GET .../evidence/{id}/extractions`, `GET .../segments?page=2` on a PDF.

Nothing in this checklist has been performed in a browser by the assistant.
