# Evidence Processing — Testing Strategy

## Principles
- Deterministic, small fixtures generated inside the tests. No model downloads, no
  network, no AI.
- Real libraries where they are installed pip packages (PyMuPDF, Pillow, openpyxl,
  stdlib). Fakes only where the dependency is a large model or an external binary.
- Tests that need the Tesseract binary or a Whisper model use `skipif` with an
  explicit reason and are reported as **skipped**, never as passed.
- Test layout: `tests/unit/` for pure logic, `tests/integration/` for API plus
  database plus storage, `tests/fixtures/` for generators.

## Fixture generators (`tests/fixtures/processing_samples.py`)
| Need | How it is built |
|---|---|
| Multi-page text PDF | PyMuPDF: new document, 3 pages, `insert_text` at known positions |
| Scanned PDF | PyMuPDF page with only an inserted image, no text |
| Mixed PDF | page 1 text, page 2 image only |
| Encrypted PDF | `doc.save(..., encryption=..., user_pw=...)` |
| Corrupt PDF | valid PDF bytes truncated in the middle |
| Empty-page PDF | one blank page; also a zero-page edge if PyMuPDF allows it |
| Text image | Pillow draws known text on a white canvas |
| Blank image | Pillow solid colour |
| Corrupt image | PNG header followed by random bytes |
| WAV | stdlib `wave`, short sine tone; silent variant |
| CSV variants | bytes encoded as utf-8, utf-8-sig, utf-16, cp1252; delimiters `, ; tab`; ragged rows; quoted newlines; empty; header-only |
| XLSX | openpyxl: two sheets, a formula, a date, a hidden sheet; separate non-workbook ZIP and a ZIP with `vbaProject.bin` |
| EML | `email.message.EmailMessage`: headers, plain and HTML parts, two attachments, a naive date, a malformed variant |

## Cross-cutting tests (unit and integration)
| Area | Tests |
|---|---|
| State machine | pending to processing to completed; failed to processing on retry; completed is skipped without `force`; `force` replaces; `processing` within the stale window is skipped; stale `processing` is reclaimed |
| Atomic claim | second claim on the same item returns zero rows |
| Failure isolation | batch of three where the middle extractor raises: item 1 and 3 completed, item 2 failed with a code, no partial segments for item 2 |
| Run history | three runs (initial plus two forced) give run numbers 1, 2, 3, exactly one current (the latest), all earlier segments still readable by `extraction_id`, and segment ids differ per run |
| Failed forced run | adds a `failed` run row, keeps the previous run current and readable, evidence shows `failed` with `has_current_extraction` true |
| One current run | the partial unique index rejects a second current run for the same evidence (tested at database level) |
| Persist atomicity | a failure while inserting segments leaves no new run, no segments and the previous current run untouched (file-backed database, real commits and rollbacks) |
| History cascade | deleting the evidence item removes every run and segment |
| Error codes | each `ExtractionError` subclass maps to its code; unknown exception maps to `internal_error` with a generic message |
| No content in errors or logs | error text contains no extracted text or path (assert on caplog and stored error) |
| Case isolation | every read and write endpoint returns 404 for a mismatched case; process-pending in case A never touches case B; identical content in two cases gives two extractions |
| Cascade | deleting an evidence item or a case removes extraction and segments |
| Locator integrity | for every segment type, promoted `page`, `t_start`, `t_end` equal the locator values; invalid locators are rejected |
| API contract | 202 shapes, 409 on retry of a non-failed item, pagination limits, `page` and `segment_type` filters, no storage path in any response |
| Background behavior | upload does not trigger extraction; process returns 202 before the job result is needed (job observed through the status endpoint) |
| Migrations | `upgrade head` on empty DB; on DB seeded at `0002` with an evidence row (row survives, new columns default correctly); `downgrade` runs |
| Config | missing optional library yields `dependency_missing`, application still imports and serves cases |
| Stage 1 and 2 regression | full existing suite unchanged, run explicitly |

## Per-format matrix
### CSV
Unit: encoding order (utf-8, BOM, utf-16 with BOM, cp1252 fallback warning), delimiter detection, header handling (blank, duplicate), type hints, no value mutation (byte-for-byte source string equality), ragged rows, quoted newlines (line number versus row number), row limit truncation, cell truncation flag, NUL rejection, empty and header-only files.
Integration: upload, process, read segments, verify row and column references.

### XLSX
Unit: coordinates for sparse rows, header detection, formula text plus cached value, missing cached value flag, date to ISO with number format retained, hidden sheet flag, macro binary warning, `DEFUSEDXML is True`, row limit across sheets.
Validation: non-workbook ZIP rejected, entry-count and uncompressed-size limits, corrupt ZIP rejected, OLE-encrypted workbook rejected with a clear message.
Integration: two-sheet workbook produces segments with correct `sheet`, `row`, `range`; cell `coord` values match the openpyxl fixture.

### EML
Unit: header segments, raw versus parsed addresses, date with and without timezone (`tz_known`), multipart alternative, HTML to text removes script and style, hidden-style flag, link list as text, attachment name sanitization, attachment sizes and hashes, MIME defects as warnings, no-header file rejected, opaque body gives `partial`.
Integration: process and verify header, body and attachment segment locators.

### PDF
Unit: block segments carry page and bbox within page bounds; per-page summary; multi-page order; scanned gives `needs_ocr`; mixed gives `partial` listing pages; encrypted gives `password_required`; truncated gives `corrupt_file`; blank gives `empty`; page limit gives `partial`; repaired warning when applicable.
Integration: process, read segments filtered by `page`.

### Image
Unit (no Tesseract needed): `group_words_into_lines` with stubbed data (ordering, union box, confidence mean, `-1` filtering), low-confidence outcome, empty outcome, pixel-limit failure, corrupt image failure, EXIF orientation, missing-binary failure via patched lookup.
Real engine (skipped if Tesseract absent): generated text image returns the known words; blank image returns `empty`.
Integration: process with a fake OCR engine registered, verify segments and locators.

### Audio
Unit: fake transcriber segments map to `AudioLocator` with ordered start and end times; probability from log-probability stays within 0 to 1; silent audio gives `empty`; undecodable audio gives `corrupt_file`; missing model gives `model_unavailable` with the download command; no download is attempted when `WHISPER_ALLOW_DOWNLOAD=false`.
Real model (skipped unless the configured model is present): generated tone or a small speech sample transcribes without error and segments have increasing timestamps. No accuracy figure is asserted or reported.
Integration: process with the fake transcriber; verify timestamps through the API.

## Reporting
- Report exact counts: passed, failed, skipped (with reasons), warnings.
- Never present skipped real-engine tests as verification of OCR or transcription
  quality. Real-engine verification is a separate manual step against the dataset.
- Do not quote accuracy, word-error-rate or confidence statistics as quality
  results.
