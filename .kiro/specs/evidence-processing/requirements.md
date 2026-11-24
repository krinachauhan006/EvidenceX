# Evidence Processing — Requirements

## Introduction
Stage 3 turns uploaded evidence into **readable, structured, source-verifiable
content**. Each evidence item is processed by a format-specific extractor that
produces ordered *segments*. Every segment records exactly where in the original
file its content came from (PDF page and box, image box, audio time range, CSV row
and column, XLSX sheet and cell, email part). Later stages (claims, entities,
contradictions) will anchor to these segments.

This spec supersedes the Stage 3 entry named "document-processing" in the
implementation plan. It adds CSV, XLSX and EML, which were not part of the original
plan.

## Boundaries (out of scope)
Gemini or any AI, claim extraction, entity/event analysis, contradiction detection,
timeline analysis, fraud/deception scoring, investigation conclusions, reports.
Also out of scope: recursive processing of email attachments, handwriting
recognition, table-structure reconstruction from images, speaker diarization,
translation, and any Redis/Celery/microservice infrastructure.

## Formats
| Evidence type | Extensions | Engine |
|---|---|---|
| document | `.pdf` | PyMuPDF |
| image | `.png .jpg .jpeg .webp` | Tesseract via pytesseract (Pillow for decoding) |
| audio | `.wav .mp3 .m4a` | faster-whisper |
| tabular (new) | `.csv`, `.xlsx` | stdlib `csv`, openpyxl |
| email (new) | `.eml` | stdlib `email` |

`tabular` and `email` are new values of `evidence_type`. The column is a plain
string, so no schema change is needed for the new values.

## Requirements

### Requirement 1 — Processing lifecycle
**User story:** As an investigator, I want to see where each file is in
processing, so that I know what is ready to inspect.

#### Acceptance criteria
1. Each evidence item SHALL have exactly one of the states `pending`, `processing`,
   `completed`, `failed`.
2. Allowed transitions SHALL be: `pending -> processing`, `failed -> processing`,
   `processing -> completed`, `processing -> failed`, and `completed -> processing`
   only when reprocessing is explicitly forced.
3. A transition into `processing` SHALL be atomic (a conditional database update),
   so two concurrent requests cannot both process the same item.
4. WHEN processing starts THEN the system SHALL record `processing_started_at`,
   clear the previous error, and increment `processing_attempts`.
5. WHEN processing ends THEN the system SHALL record `processing_completed_at`.
6. An item stuck in `processing` for longer than `PROCESSING_STALE_MINUTES` (for
   example after a server restart) SHALL be treated as reclaimable by the next
   process or retry request.
7. Existing evidence rows created in Stage 2 SHALL remain valid and show as
   `pending` without any data change.

### Requirement 2 — Triggering and idempotency
1. The system SHALL support processing one evidence item, all `pending` items in a
   case, and retrying `failed` items.
2. WHEN a `completed` item is processed again without `force` THEN the system SHALL
   NOT re-extract and SHALL report it as skipped with reason `already_completed`.
3. WHEN `force=true` is supplied for a `completed` item THEN the system SHALL
   create a NEW extraction run and make it the current one, in a single
   transaction. Earlier runs and all of their segments SHALL be preserved
   unchanged. A failed forced run SHALL leave the previous current run intact and
   current.
4. WHEN an item is already `processing` and not stale THEN a new request SHALL be
   skipped with reason `already_processing`.
5. Retry SHALL be accepted only for `failed` items (409 otherwise).
6. "Process all pending" SHALL queue only `pending` items. It SHALL NOT silently
   retry `failed` items.
7. An item whose file type has no extractor available in the running build SHALL
   be skipped with reason `no_extractor` and SHALL stay `pending`. It SHALL NOT be
   marked `failed`.

### Requirement 3 — Non-blocking execution
1. Upload requests SHALL NOT perform extraction.
2. Process/retry requests SHALL return `202 Accepted` immediately. Extraction SHALL
   run in a FastAPI `BackgroundTasks` job with its own database session.
3. Heavy extraction (OCR, audio) SHALL be limited by `PROCESSING_MAX_CONCURRENCY`
   (default 1) so a batch cannot exhaust memory.
4. A batch SHALL process items sequentially and independently.
5. No Redis, Celery or extra service SHALL be introduced.

### Requirement 4 — Failure isolation and error reporting
1. An exception while processing one item SHALL mark only that item `failed` and
   SHALL NOT stop the rest of the batch or the application.
2. A failed item SHALL store a human-readable `processing_error` and a
   machine-readable `processing_error_code`.
3. Error codes SHALL include at least: `corrupt_file`, `password_required`,
   `unsupported_content`, `dependency_missing`, `model_unavailable`,
   `limit_exceeded`, `timeout`, `storage_missing`, `internal_error`.
4. A failed run SHALL NOT leave partial segments. Segment writes and the status
   update to `completed` SHALL happen in one transaction.
5. Error messages SHALL NOT include extracted file content or filesystem paths.
6. WHEN a required dependency (Tesseract binary, Whisper model, Python package) is
   missing THEN the item SHALL fail with `dependency_missing` or
   `model_unavailable` and a message that says what to install or configure. The
   application SHALL keep running.

### Requirement 5 — Extraction data model and provenance
1. Each evidence item SHALL have an append-only history of **extraction runs**.
   Every run SHALL hold: extraction id, evidence id, case id, run number (1, 2, 3
   in order of attempt), run status (`completed` or `failed`), extractor name and
   version, source SHA-256 at extraction time, outcome (completed runs), error code
   and message (failed runs), document-level metadata, warnings, start time,
   record time and duration. At most one completed run per evidence item SHALL be
   marked **current**, enforced by the database. Reads default to the current run
   and can address any earlier run by id.
2. An extraction SHALL have zero or more ordered **segments**. Each segment SHALL
   hold: segment id, extraction id, evidence id, case id, sequence number, segment
   type, extracted `text` (nullable), structured `data` (nullable), a typed
   `locator`, and engine-reported confidence where the engine provides one.
3. The `locator` SHALL be a discriminated type with these shapes:
   - PDF: `page` (1-based), `bbox` `[x0,y0,x1,y1]` in PDF points, page width and
     height.
   - Image: `bbox` in pixels, image width and height.
   - Audio: `start` and `end` in seconds.
   - CSV: `row` (1-based record number), `line` (first physical line of the
     record) and `column` (null when the segment is the whole row).
   - XLSX: `sheet`, `row`, and cell `range`. Each cell inside `data` SHALL carry its
     own coordinate (for example `C5`).
   - EML: `part` (`header`, `body_text`, `body_html`, `attachment`) plus a header
     name or part index.
4. Page, start time and end time SHALL also be stored in queryable columns and SHALL
   always equal the values inside `locator`.
5. The extraction outcome SHALL be one of `ok`, `partial`, `needs_ocr`, `empty`.
   `needs_ocr` and `empty` SHALL never be reported as plain success.
6. Engine confidence (OCR word confidence, Whisper segment probability) SHALL be
   stored in `engine_confidence` (0 to 1) and SHALL be described in the UI as
   engine-reported, not as a statement about factual accuracy. It SHALL stay
   separate from the claim-level `extraction_confidence` defined for Stage 4.
7. The original evidence file and its SHA-256 SHALL NOT be changed.
8. Segment text SHALL be the extractor's output, never a rewritten or "corrected"
   version. For structured data the raw cell values SHALL be preserved in `data`.
9. Deleting an evidence item or a case SHALL cascade-delete its extraction and
   segments.
10. Migrations SHALL be additive and SHALL NOT alter or delete existing rows.
11. Segments belong to one specific run and SHALL NOT be moved, rewritten or
    deleted when a later run is created. Later stages anchor claims to segment ids,
    so those anchors stay valid after reprocessing.
12. Run numbers are the evidence item's attempt counter at claim time. A gap in the
    sequence means an attempt was interrupted before it could record a result.
13. Deleting an evidence item or a case SHALL remove its whole run history. No
    retention policy is applied in this stage.

### Requirement 6 — PDF extraction (PyMuPDF)
1. The extractor SHALL read text from every page, in reading order, as text-block
   segments. Each segment SHALL carry its page number and block bounding box.
2. The extraction metadata SHALL include page count, the PDF information fields
   when present (title, author, subject, creator, producer, creation and
   modification dates as raw strings), and a per-page summary (page number,
   width, height, character count, image count, has-text flag).
3. A PDF whose pages contain no text layer but do contain images SHALL produce
   outcome `needs_ocr` with a warning naming the affected pages. Status SHALL be
   `completed` and the UI SHALL show "Requires OCR".
4. A PDF where only some pages have no text SHALL produce outcome `partial` with a
   warning listing those pages.
5. A PDF with zero pages or no content at all SHALL produce outcome `empty`.
6. A corrupt or unreadable PDF SHALL fail with `corrupt_file`.
7. A PDF that needs a password to open SHALL fail with `password_required`. The
   system SHALL NOT attempt to guess passwords.
8. A PDF that opens without a password but is flagged encrypted SHALL be extracted
   and carry the warning `encrypted_no_user_password`.
9. A PDF that PyMuPDF had to repair SHALL carry the warning `pdf_repaired`.
10. Documents above `MAX_PDF_PAGES` SHALL be truncated at the limit with outcome
    `partial` and warning `page_limit_reached`.
11. JavaScript, embedded files and external links in the PDF SHALL NOT be executed
    or followed. Embedded file names MAY be listed in metadata.

### Requirement 7 — Image OCR (Tesseract)
1. The extractor SHALL decode the image with Pillow, apply EXIF orientation, and
   run Tesseract to obtain words with boxes and confidences.
2. Words SHALL be grouped into line segments. Each line segment SHALL carry its
   pixel bounding box, text, and mean word confidence (0 to 1). Word boxes and
   confidences SHALL be kept in the segment `data`.
3. Extraction metadata SHALL include image width, height, format, OCR language, and
   mean confidence over all words.
4. An image with no recognized text SHALL produce outcome `empty` with warning
   `no_text_detected`.
5. WHEN mean confidence is below `OCR_MIN_CONFIDENCE` THEN the outcome SHALL be
   `partial` with warning `low_confidence`, and the text SHALL still be stored.
6. WHEN the Tesseract binary or language data is missing THEN the item SHALL fail
   with `dependency_missing` and a message that names `TESSERACT_CMD` and the
   install step. The rest of the application SHALL be unaffected.
7. Images above `MAX_IMAGE_PIXELS` SHALL fail with `limit_exceeded` (no
   decompression-bomb decode). Corrupt images SHALL fail with `corrupt_file`.
8. Table layout SHALL NOT be reconstructed. Table text is returned as OCR lines
   with their positions.

### Requirement 8 — Audio transcription (faster-whisper)
1. The extractor SHALL transcribe with faster-whisper and store one segment per
   transcript segment with `start`, `end` (seconds), text, and a probability
   derived from the engine's average log-probability.
2. Extraction metadata SHALL include audio duration, detected language and
   language probability, model size, device and compute type.
3. Raw engine values (`avg_logprob`, `no_speech_prob`, `compression_ratio`) SHALL be
   kept in the segment `data`.
4. Audio with no speech SHALL produce outcome `empty` with warning
   `no_speech_detected`.
5. The Whisper model SHALL be configurable (`WHISPER_MODEL_SIZE`, `WHISPER_MODEL_DIR`,
   `WHISPER_DEVICE`, `WHISPER_COMPUTE_TYPE`, `WHISPER_LANGUAGE`).
6. The system SHALL NOT download a model automatically. WHEN the model is not
   present locally and `WHISPER_ALLOW_DOWNLOAD` is not `true` THEN the item SHALL
   fail with `model_unavailable` and a message giving the explicit download
   command. A separate command-line tool SHALL perform the download only after the
   developer runs it.
7. A corrupt or undecodable audio file SHALL fail with `corrupt_file`.
8. The UI and API text SHALL describe transcripts as machine transcription. They
   SHALL NOT claim the content is true or the recording is authentic.

### Requirement 9 — CSV extraction
1. The extractor SHALL detect encoding in this order: UTF-8 with or without BOM,
   UTF-16 (BOM present), then Windows-1252 as a last resort. The detected encoding
   SHALL be stored; a fallback SHALL add the warning `encoding_assumed`.
2. The delimiter SHALL be detected from `, ; tab |` and stored. If detection fails
   the comma SHALL be used and a warning added.
3. The first non-blank record SHALL be treated as the header row. Raw header text
   SHALL be preserved. Blank or duplicate headers SHALL get unique working keys
   (`column_3`, `Amount__2`) while the raw header is kept.
4. Row numbers count every record the CSV reader returns, including blank ones, so
   they match the row numbers a spreadsheet program shows. Blank records produce no
   segment and are counted in metadata. Every data record SHALL become a segment
   with its row number and the first physical line of the record.
5. Each cell SHALL be stored as `{column, index, value, type_hint}`. `value` SHALL be
   the exact source string. `type_hint` is advisory only: `integer`, `decimal`,
   `boolean`, `empty`, `text`.
6. The extractor SHALL NOT convert, trim, reformat or reinterpret values, and SHALL
   NOT parse dates.
7. Rows with more or fewer cells than the header SHALL be kept as read (extra cells
   named `extra_N`) and counted in a `ragged_rows` warning with the first affected
   row numbers.
8. An empty file or a file with only whitespace SHALL produce outcome `empty`.
   A file with headers and no data rows SHALL produce `empty` with warning
   `no_data_rows`, and the headers SHALL still be stored.
9. Files above `MAX_TABULAR_ROWS` SHALL be truncated with outcome `partial` and
   warning `row_limit_reached`. Cells longer than `MAX_CELL_CHARS` SHALL be
   truncated and flagged.
10. Binary content (NUL bytes outside UTF-16) SHALL fail with `corrupt_file`.

### Requirement 10 — XLSX extraction (openpyxl)
1. The extractor SHALL open the workbook read-only, from memory, with safe XML
   parsing (defusedxml present).
2. Workbook metadata (creator, last modified by, created, modified, title) and the
   ordered list of worksheets with state (`visible`, `hidden`, `veryHidden`) SHALL
   be stored. Hidden sheets SHALL be extracted and flagged with a warning.
3. For each worksheet the first non-empty row SHALL be treated as the header row.
   Every non-empty row SHALL become a segment with `sheet`, `row` and `range`.
4. Each cell in `data` SHALL carry `coord` (for example `C5`), `column` (header
   text), `value`, `type_hint`, and `number_format`.
5. Formula cells SHALL store the formula text (for example `=SUM(B2:B9)`) and the
   cached value. WHEN no cached value exists THEN `value` SHALL be null and the
   cell SHALL carry `no_cached_value`. Formulas SHALL NOT be evaluated.
6. Date-formatted cells SHALL be stored as ISO 8601 strings with the original
   `number_format` kept. No timezone SHALL be invented.
7. Multiple worksheets SHALL be supported and kept distinct by sheet name.
8. A workbook containing `xl/vbaProject.bin` SHALL be extracted with warning
   `contains_macro_binary`. Macros SHALL NOT be run.
9. Corrupt workbooks, non-workbook ZIP files, and password-protected (OLE
   encrypted) workbooks SHALL fail with `corrupt_file` or `password_required`.
10. ZIP bombs SHALL be rejected at upload validation (entry-count and total
    uncompressed-size limits).
11. The extractor SHALL document the read-only limits: merged-cell ranges, cell
    comments, charts and embedded images are not extracted.
12. Row limits from Requirement 9.9 SHALL apply across the workbook.

### Requirement 11 — EML extraction
1. The extractor SHALL parse with Python's `email` package using the default policy.
   It SHALL NOT execute, render or fetch anything from the message.
2. Header segments SHALL be created for From, To, Cc, Subject, Date, Message-ID,
   In-Reply-To and References when present. Raw header text SHALL be preserved and
   parsed addresses stored alongside it. Reply-To, Return-Path and the list of
   Received headers SHALL be kept in extraction metadata as raw strings.
3. Date SHALL be stored raw, plus an ISO value only when it parses. WHEN the parsed
   date has no timezone THEN `tz_known=false` SHALL be recorded. Values SHALL NOT be
   converted to UTC silently.
4. Plain-text body parts SHALL become `body_text` segments, one per part.
5. HTML body parts SHALL be converted to text by a safe converter that drops
   `script`, `style` and `template` content, never loads resources, and lists link
   targets as plain text in `data`. The HTML source SHALL NOT be stored for display.
   Hidden-styled content SHALL be flagged with warning `html_hidden_content`.
6. Each attachment SHALL become an `attachment` segment with filename (sanitized for
   display), MIME type, decoded size and SHA-256. Attachment content SHALL NOT be
   parsed or stored.
7. MIME defects reported by the parser SHALL be listed as warnings.
8. A file with no recognizable message headers SHALL fail with `corrupt_file`.
9. Encrypted or opaque bodies (for example `application/pkcs7-mime`) SHALL produce
   outcome `partial` with warning `body_not_readable`.

### Requirement 12 — Upload validation for new formats
1. `.csv`, `.xlsx` and `.eml` SHALL be accepted by upload with a server-resolved
   type and MIME (`text/csv`, the OOXML spreadsheet type, `message/rfc822`).
2. XLSX SHALL be accepted only if it is a ZIP that contains `[Content_Types].xml`
   and `xl/workbook.xml`, within the entry-count and uncompressed-size limits.
3. CSV SHALL be rejected when it is binary (known binary signatures, or NUL bytes
   that are not UTF-16).
4. EML SHALL be rejected unless the first lines parse as RFC 5322 headers and at
   least one common message header is present.
5. All Stage 2 validation rules and tests SHALL continue to apply unchanged for the
   existing formats.

### Requirement 13 — API
Endpoints are listed in `design.md`. Requirements:
1. Process, retry and process-pending SHALL return `202` with the lists of queued
   and skipped items (with reasons).
2. Status, extraction summary and segment endpoints SHALL be read-only.
3. Segments SHALL be paginated (`limit` default 100, maximum 500) and filterable by
   `page` and `segment_type`.
4. Responses SHALL NOT include storage paths.
5. A case-level summary endpoint SHALL return counts per status and per-item
   status, outcome and segment count, for the progress indicator.
6. History endpoints SHALL list all runs for an evidence item (newest first), fetch
   one run, and read the segments of any run. Without a run id, segment reads use
   the current run.

### Requirement 14 — Case isolation
1. Every endpoint SHALL resolve evidence by `(case_id, evidence_id)`. A mismatch SHALL
   return 404 and SHALL NOT reveal extraction data.
2. Segment and extraction queries SHALL be filtered by `case_id` and `evidence_id`.
3. Process-pending SHALL only touch evidence in the requested case.
4. Identical file content in two cases SHALL produce two independent extractions.

### Requirement 15 — Frontend
The existing Evidence section SHALL be extended, not redesigned. Upload, download
and delete SHALL keep working as before.
1. Each row SHALL show filename, type icon, upload date, size, processing status,
   error text when failed, and extraction availability (outcome and segment count).
2. Status presentation: `pending` neutral, `processing` neutral with a spinner,
   `completed` green, `failed` a distinct failure style. `needs_ocr` and `empty`
   SHALL show a neutral notice, not the green success style.
3. Row actions: Process (pending, with an extractor), Retry (failed), Re-process
   (completed, with confirmation because it creates a NEW extraction run that
   becomes current; earlier runs are kept), View extraction (any item that has a
   run). The extraction viewer lists the run history and lets the user open any
   earlier run and read that run's segments.
4. Section actions: "Process all pending (N)" and an overall progress bar showing
   completed, processing, pending and failed counts.
5. The UI SHALL poll status while any item is `processing` or queued and SHALL stop
   when none are.
6. The extraction viewer SHALL show the extractor name and version, outcome,
   warnings, metadata, and a paginated segment list. Every segment SHALL show a
   readable source reference: `Page 3`, `00:01:12.3 - 00:01:18.9`,
   `Sheet "Payments" - C5`, `Row 14 - Amount`, `Header: Subject`, `Body (text)`.
7. Extracted text SHALL be rendered as plain text only. The UI SHALL NOT use
   `dangerouslySetInnerHTML`, and link targets SHALL be shown as text, not links.
8. Engine confidence SHALL be labeled "engine-reported confidence" with a note that
   it is not a measure of factual accuracy.
9. The viewer SHALL show loading, empty, error and "no extraction yet" states.
10. Amber SHALL stay reserved for potential inconsistencies. New failure styling SHALL
    use a separate token.
11. Claim analysis, contradiction charts and dashboards SHALL NOT be added.

### Requirement 16 — Security
1. File type SHALL be validated by content, not by extension or MIME alone.
2. Storage paths SHALL come only from the content hash and SHALL NOT be exposed.
3. Extractors SHALL receive bytes from storage. They SHALL NOT receive or build
   paths from user input.
4. Extracted text SHALL be treated as untrusted data everywhere. No code path SHALL
   interpret it as instructions.
5. Logs SHALL contain ids, extractor names, outcomes, counts and durations. They
   SHALL NOT contain extracted text or file bytes.
6. Limits SHALL be enforced: file size (existing), PDF pages, image pixels, tabular
   rows, cell length, total extracted characters, ZIP entries and uncompressed size.
7. Native-library parsing risk SHALL be isolated behind an `ExtractionExecutor`
   interface so a subprocess executor can be added without changing extractors.

### Requirement 17 — Configuration and dependencies
1. All limits, engine options and model settings SHALL come from environment
   variables with safe defaults (listed in `design.md`) and appear in
   `.env.example`.
2. The application SHALL start and serve Stage 1 and Stage 2 features even when OCR,
   audio or PDF libraries are not installed. Missing engines SHALL surface only as
   per-item `dependency_missing` failures.
3. Heavy libraries SHALL be imported lazily inside extractors.

### Requirement 18 — Tests and reporting
1. Each format SHALL have unit and integration tests as listed in `testing.md`.
2. Tests SHALL be deterministic, use small generated fixtures, and SHALL NOT download
   models or call external services.
3. Tests that need the real Tesseract binary or a real Whisper model SHALL be skipped
   with an explicit reason when the dependency is absent, and SHALL be reported as
   skipped, never as passed.
4. All Stage 1 and Stage 2 tests SHALL continue to pass. The only permitted edit to
   an existing test is the Stage 2 assertion that supported extensions equal the
   sample set, which must grow with the new formats.
5. Reported results SHALL come from the real test runner.

## Acceptance summary per format
| Format | Done when |
|---|---|
| PDF | Multi-page fixture yields block segments with page and bbox; scanned fixture yields `needs_ocr`; encrypted, corrupt and empty fixtures behave as in R6. |
| Image | Generated text image yields line segments with bbox and confidence (when Tesseract is present); blank image yields `empty`; missing Tesseract yields `dependency_missing`. |
| Audio | Fake-transcriber test yields timestamped segments in order; real-model test passes when a model is present; missing model yields `model_unavailable`. |
| CSV | UTF-8, UTF-8 BOM, UTF-16, cp1252, semicolon and tab fixtures parse; ragged rows kept and flagged; values byte-identical to source. |
| XLSX | Two-sheet fixture with a formula and a hidden sheet yields correct sheet, row and coordinates; macro and non-workbook ZIP cases behave as in R10. |
| EML | Fixture with headers, plain and HTML parts and two attachments yields header, body and attachment segments; HTML script content is absent from text. |
