# Evidence Processing — Tasks

Status below reflects the implementation as verified by the automated suite and the
checks listed in `foundation-mvp.md`. A box is ticked only when the work exists AND is
covered by a passing test or check. Items that need a person (a model download, a
dataset walk-through, a browser check) are left unticked and say so.

Rules for every phase:
- Tests ship with the code. Run `pytest`, `ruff`, and (for UI phases) `typecheck`,
  `lint` and `build`. Report actual output. Stop at the first blocking error.
- Do not modify unrelated modules. Preserve all Stage 1 and Stage 2 behavior.
- Do not use `create_all()` as a migration substitute. Do not reset any database.
- Do not add Gemini, claim, entity, contradiction or timeline code.

---

## Phase 0 — Prerequisites and baseline  — DONE
- [x] 0.1 Baseline recorded (79 backend tests at the time).
- [x] 0.2 Development database backed up before the first migration.
- [x] 0.3 Packages installed and imports verified (pymupdf 2.1, pillow 13.0.0,
      pytesseract 0.3.13, openpyxl 3.1.5, defusedxml 0.7.1, faster-whisper 1.2.1).
- [x] 0.4 `pyproject.toml` (core deps plus `audio` extra) and `.env.example`.
- [x] 0.5 Tesseract installed at `C:\Program Files\Tesseract-OCR\tesseract.exe`
      (found automatically; `TESSERACT_CMD` is only needed for another location).

## Phase 1 — Foundation and CSV vertical slice  — DONE
Append-only extraction run history (requirements 5.1, 5.11-5.13). Delimiter detection
is a deterministic field-count check, not `csv.Sniffer`.
- [x] 1.1 Settings. [x] 1.2 Migrations `0003`, `0004`. [x] 1.3 Evidence model/schema.
- [x] 1.4 Processing module, locators, errors, limits, registry, executor.
- [x] 1.5 Repository: atomic claim, record success/failure, scoped reads.
- [x] 1.6 Runner: concurrency guard, stale reclaim, failure isolation, one transaction.
- [x] 1.7 Service and router. [x] 1.8 CSV validation. [x] 1.9 CSV extractor.
- [x] 1.10 SQLite busy timeout and WAL. [x] 1.11 Test fixtures. [x] 1.12 Tests.

## Phase 2 — Frontend processing UI  — DONE
Manual browser checks passed (viewer, run history, pagination, download, delete).
- [x] 2.1-2.6 Types, client, polling hook, row/badge/toolbar, viewer, segment items.

## Phase 3 — EML and XLSX  — DONE
- [x] 3.1 Upload validation. XLSX: shared ZIP guard (`app/core/zip_safety.py`) with
      entry-count, total-size, per-entry, shared-strings and compression-ratio limits,
      forged-header and CRC checks, OLE rejection. EML: real RFC 5322 header block.
- [x] 3.2 `html_text.py` and `eml.py`.
- [x] 3.3 `xlsx.py`: formulas kept as text, cached values, dates with number format,
      serial and date system, hidden sheets, macro flag, sparse rows, wrong dimension
      records. The same ZIP limits run again before parsing.
- [x] 3.4 Tests for both formats, including entity-expansion and ZIP-bomb cases.
- [x] 3.5 Stage 2 sample-extension test updated (`SAMPLES` has xlsx and eml).

## Phase 4 — PDF  — DONE
- [x] 4.1 `pdf.py`: text blocks with page and box, per-page summary, scanned-page
      detection, encryption and repair warnings, page and character limits.
- [x] 4.2 Tests with PDFs generated in the test (multi-page, scanned, mixed, blank,
      encrypted, corrupt).
- Licensing: PyMuPDF is AGPL-3.0 or commercial. `PDF_EXTRACTION_ENABLED=false` turns
  PDF processing off. See `foundation-mvp.md`.

## Phase 5 — Image OCR  — DONE
- [x] 5.1 Tesseract present and discovered (PATH, `TESSERACT_CMD`, default folder).
- [x] 5.2 `ocr_engine.py` (pure line grouping + Tesseract adapter), `image_ocr.py`.
- [x] 5.3 Unit tests with stubbed word data and a fake engine; real-engine tests run
      when Tesseract is installed and are skipped (reported as skipped) otherwise.
- [x] 5.4 Scanned PDF pages are rendered and OCR'd (`PDF_OCR_FALLBACK`), boxes mapped
      back to PDF points. (Originally optional task 7.2.)

## Phase 6 — Audio  — IMPLEMENTED, REAL MODEL NOT YET RUN
- [x] 6.1 `Transcriber` protocol, faster-whisper implementation, `local_files_only`.
- [x] 6.2 `app/tools/fetch_whisper_model.py` (prints size, asks to confirm).
- [x] 6.3 `audio.py` mapping segments to `AudioLocator`, silent-audio handling.
- [x] 6.4 Tests with a fake transcriber and a generated WAV; missing-model failure test.
- [ ] 6.5 NEEDS A PERSON: run the download command (about 145 MB for `base`) and process
      a real recording. Until then audio items fail with `model_unavailable` and a
      message that names the command. No transcription quality has been measured.

## Phase 7 — Optional hardening  — NOT DONE (not required for the MVP)
- [ ] 7.1 `SubprocessExecutor` with a hard timeout. Extraction currently runs inline
      with size, row, page, pixel and character limits but no wall-clock limit except
      the OCR timeout. A hostile file can still hold a worker thread.
- [x] 7.2 PDF OCR fallback (done in 5.4).
- [ ] 7.3 Crash/timeout isolation tests (depend on 7.1).

## Phase 8 — Documentation and final verification
- [x] 8.1 Full backend run (`pytest`, `ruff`) and frontend `typecheck`, `lint`, `build`.
- [x] 8.2 Stage 1 and 2 regression tests run as part of the full suite.
- [ ] 8.3 NEEDS A PERSON: walk the dataset in the UI and compare with `ground_truth`.
- [x] 8.4 Documentation: this file, `foundation-mvp.md`, `.env.example`.

---

## Dependencies between phases
```
P0 -> P1 -> P2
        \-> P3 -> (P4, P5, P6 independent of each other)
P1..P6 -> P8        P7 optional
```

## Acceptance criteria
A phase is accepted when its tests pass in the real runner, ruff is clean, the
checkpoint works, existing tests still pass, and no skipped test is reported as passed.
