# Evidence Processing — Design

> **Status note.** Section 1 below records the project as it was when this design was
> written. It is kept as history. The packages it lists as "not installed" are installed,
> Tesseract is installed, and every extractor in section 8 is implemented. For the
> current state, limits, warnings, setup and known gaps see `foundation-mvp.md`. Two
> deliberate differences from the text below: extraction runs behind `InlineExecutor`
> only (the subprocess executor is not built), and scanned PDF pages are OCR'd when
> Tesseract is available (`PDF_OCR_FALLBACK`).

## 1. What the existing code gives us (inspected, not assumed)

| Area | Current state | Consequence for Stage 3 |
|---|---|---|
| Evidence model | `evidence` already has `processing_status` (default `pending`) and `processing_error`. `evidence_type` is a plain `String(16)`. | Reuse both columns. New types `tabular` and `email` need no migration. Add only new timing, attempt and error-code columns. |
| Storage | `LocalStorage` (content-addressed): `put_stream`, `open`, `delete`, `exists`, `path_for`. | Extractors read bytes through `storage.open()`. No path ever reaches an extractor or a response. |
| Validation | `validation.py` checks extension plus a 32-byte signature. | CSV, XLSX and EML cannot be validated from 32 bytes. Add a second, deeper content check that runs on the already-buffered upload. |
| Upload service | Buffers the upload (max 25 MB) in memory, then streams to storage. | The full content is already in memory at validation time, so deep checks (ZIP listing, header parse) are cheap. |
| DB access in requests | `get_db` yields a per-request session. | A background job cannot reuse it (closed after the response). The job opens its own session from an injectable factory. |
| Tests | One shared SQLite connection per test, wrapped in a rolled-back transaction. `TestClient` runs background tasks before returning. | The job's session factory must be overridable to return the test session. Background work is then observable inside a test. |
| Case delete | Calls evidence blob cleanup, then relies on FK cascade. | New tables use `ON DELETE CASCADE` on `evidence_id` and `case_id`, so no change to case deletion. |
| Frontend | `EvidenceSection` (one client component) owns upload, list, delete. `apiFetch`, `apiUpload`, `ACCEPTED_EXTENSIONS` exist. | Extend it with sub-components. Keep its upload and delete behavior untouched. |
| Environment | Python 3.13.15, ffmpeg on PATH. PyMuPDF, Pillow, pytesseract, openpyxl, faster-whisper are **not installed**. **Tesseract binary is not installed.** | Installation is a prerequisite step (section 13). |
| Wheel check | `pip install --dry-run --only-binary=:all:` resolved `ctranslate2 4.9.0 cp313 win_amd64`, `faster-whisper 1.2.1`, `pymupdf 2.1`, `pillow 13.0.0`, `openpyxl 3.1.5`, `pytesseract 0.3.13`. | Python 3.13 is supported. Older reports of missing 3.13 wheels are outdated. |

**Conflicts found and how they are resolved**
1. The Stage 2 unit test `test_all_supported_extensions_have_samples` asserts that supported extensions equal the sample set. It must grow with the new formats. This is the only existing test that changes.
2. Steering `safety-and-provenance.md` invariant 2 lists locators only for PDF, image and audio. CSV, XLSX and EML locators are added (section 12).
3. Steering names the confidence field `extraction_confidence` for claim extraction. Engine confidence from OCR and Whisper uses a different name, `engine_confidence`, to keep the two apart.
4. Existing UI uses the amber token for delete and error states. Steering reserves amber for inconsistencies. New failure states use a separate token and existing styling is left unchanged (decision D5).

## 2. Architecture

```
POST .../process | process-pending | retry            (202, returns immediately)
        |
        v
ProcessingService.enqueue()  --- conditional checks, builds queued/skipped lists
        |  BackgroundTasks.add_task(runner.run_batch, case_id, [evidence_id...], force)
        v
ProcessingRunner.run_batch()           (own DB session, sequential)
   for each id:
     claim()   atomic UPDATE pending/failed -> processing   (skip if lost the race)
     load blob via Storage.open()
     ExtractionExecutor.run(extractor, input)   <- inline now; subprocess later
        |  returns ExtractionResult  or raises ExtractionError
     persist(): one transaction = replace extraction + insert segments + status=completed
     on error:  rollback, status=failed + error + error_code
        v
extractions / extraction_segments / evidence.processing_*
        ^
GET .../processing | extraction | segments | case summary   (read-only, scoped)
```

Key decisions:
- **Claim at execution time, not at request time.** If the server dies after the 202 but before the job starts, the item is still `pending` and nothing is stuck. Only a crash during extraction can leave `processing`, which the stale timeout recovers.
- **Append-only extraction history.** Every attempt that reaches a result is recorded as a run (`completed` or `failed`). One completed run per evidence item is marked `is_current`, enforced by a partial unique index. Forced reprocessing adds a run and moves the current marker in one transaction. It never deletes or rewrites older runs or their segments, so Stage 4 claim anchors stay valid.
- **Extractors are pure functions of bytes.** They know nothing about the database, storage or HTTP. This makes them easy to test and to move into a subprocess.
- **Heavy imports are lazy**, so a missing library never breaks application start.

### Module layout
```
backend/app/modules/processing/
  __init__.py
  models.py          Extraction, ExtractionSegment
  schemas.py         Out models, locator union, ProcessAccepted, summaries
  locators.py        Pydantic locator types + builders that also fill promoted columns
  repository.py      claim, finish, fail, replace_extraction, queries (all case-scoped)
  service.py         enqueue / status / read APIs (request-side)
  runner.py          run_batch, run_one (background-side), concurrency guard
  executor.py        ExtractionExecutor protocol, InlineExecutor
  router.py          endpoints (mounted in main.py)
  errors.py          ExtractionError hierarchy + error codes
  registry.py        evidence extension -> extractor factory (injectable for tests)
  limits.py          ExtractionLimits dataclass built from Settings
  extractors/
    base.py          Extractor protocol, ExtractionInput, ExtractionResult, SegmentDraft
    pdf.py           PyMuPDF
    image_ocr.py     Pillow + pytesseract; pure grouping function
    audio.py         faster-whisper; Transcriber protocol; model loader
    csv_extractor.py stdlib csv
    xlsx.py          openpyxl
    eml.py           stdlib email + safe HTML-to-text
    html_text.py     HTMLParser-based converter (no third-party dependency)
backend/app/tools/
  fetch_whisper_model.py   explicit model download command (never run automatically)
```
Layering follows Stage 1 and 2: router -> service -> repository, separate `models.py` and `schemas.py`. The runner is the one addition (background-side orchestration).

## 3. Extractor contract

```python
@dataclass(frozen=True)
class ExtractionInput:
    data: bytes              # blob from storage
    filename: str            # display only, never used as a path
    mime_type: str
    sha256: str
    limits: ExtractionLimits
    options: Mapping[str, Any]   # engine settings (tesseract cmd, whisper model, ...)

@dataclass
class SegmentDraft:
    segment_type: str
    text: str | None
    data: dict | None
    locator: Locator                 # typed
    engine_confidence: float | None  # 0..1 or None
    language: str | None

@dataclass
class ExtractionResult:
    extractor: str                   # "pymupdf", "tesseract", ...
    extractor_version: str
    outcome: Literal["ok","partial","needs_ocr","empty"]
    segments: list[SegmentDraft]
    metadata: dict
    warnings: list[Warning]          # {code, message, detail?}

class Extractor(Protocol):
    def extract(self, inp: ExtractionInput) -> ExtractionResult: ...
```

Errors (all subclass `ExtractionError(code, message)`): `CorruptFileError`, `PasswordRequiredError`, `UnsupportedContentError`, `DependencyMissingError`, `ModelUnavailableError`, `LimitExceededError`. Any other exception becomes `internal_error` with a generic message (the stack trace goes to the log without file content).

`registry.py` maps `evidence_type` + extension to an extractor factory. Tests override it to inject fake extractors and a fake transcriber.

## 4. State machine and concurrency

States: `pending`, `processing`, `completed`, `failed`.

Atomic claim (one statement, rowcount decides):
```sql
UPDATE evidence
SET processing_status='processing', processing_started_at=:now,
    processing_completed_at=NULL, processing_error=NULL,
    processing_error_code=NULL, processing_attempts=processing_attempts+1
WHERE id=:id AND case_id=:case_id AND (
      processing_status IN ('pending','failed')
   OR (processing_status='completed' AND :force)
   OR (processing_status='processing' AND processing_started_at < :stale_cutoff))
```
Rowcount 0 means the item was taken or is not eligible, so it is skipped.

Forced reprocess: the previous current run stays current until the new run succeeds. On success, one transaction clears the old `is_current`, inserts the new run with its segments, and sets the evidence status. If the new run fails, a `failed` run row is recorded, the old run stays current, and the evidence shows `failed` while `has_current_extraction` remains true so the old results stay viewable.

Run numbers: the claim increments `processing_attempts`, and that value becomes the run number. If the server dies mid-run, that number is skipped (no row is written), which is visible as a gap.

Runner concurrency: a process-wide `threading.BoundedSemaphore(PROCESSING_MAX_CONCURRENCY)` wraps the extraction call. Database work happens outside it.

SQLite note: concurrent writers from threads can raise "database is locked". Mitigation: set a busy timeout and WAL mode for file-based SQLite in the existing connect listener (small additive change to `database.py`, task P1). Postgres is unaffected.

## 5. Data model

### 5.1 `evidence` (additive columns, migration `0003`)
| column | type | notes |
|---|---|---|
| `processing_started_at` | timestamptz null | set on claim |
| `processing_completed_at` | timestamptz null | set on success or failure |
| `processing_attempts` | integer not null, server default 0 | existing rows get 0 |
| `processing_error_code` | varchar(48) null | machine-readable |

Existing columns `processing_status` and `processing_error` are reused unchanged.

### 5.2 `extractions` (migration `0004`) — one row per run, append-only
| column | type | notes |
|---|---|---|
| `id` | GUID pk | |
| `evidence_id` | GUID fk -> evidence.id ON DELETE CASCADE | indexed; many runs per evidence |
| `case_id` | GUID fk -> cases.id ON DELETE CASCADE | indexed, for scoping |
| `run_number` | integer | evidence attempt counter at claim time; unique with `evidence_id` |
| `run_status` | varchar(16) | `completed` or `failed` |
| `is_current` | boolean | true for at most one completed run per evidence |
| `extractor` | varchar(32) | e.g. `csv`, `pymupdf` |
| `extractor_version` | varchar(32) | extractor/engine version string |
| `source_sha256` | varchar(64) | hash of the evidence content that was read |
| `outcome` | varchar(16) null | `ok`, `partial`, `needs_ocr`, `empty`; null for failed runs |
| `error_code`, `error_message` | varchar(48), text null | failed runs only |
| `doc_metadata` | JSON (JSONB on Postgres) | document, sheet, audio, image or email metadata |
| `warnings` | JSON | list of `{code, message, detail?}` |
| `segment_count` | integer | 0 for failed runs |
| `duration_ms` | integer | extraction time |
| `started_at` | timestamptz | claim time |
| `created_at`, `updated_at` | timestamptz | `created_at` is when the run was recorded |

Constraints: `uq_extractions_evidence_run (evidence_id, run_number)`; partial unique index `uq_extractions_current (evidence_id) WHERE is_current` (written with `sqlite_where` and `postgresql_where`); `ix_extractions_case (case_id)`. A failed run is never current.

### 5.3 `extraction_segments` (migration `0004`)
| column | type | notes |
|---|---|---|
| `id` | GUID pk | |
| `extraction_id` | GUID fk ON DELETE CASCADE | |
| `evidence_id` | GUID fk ON DELETE CASCADE | indexed |
| `case_id` | GUID fk ON DELETE CASCADE | indexed |
| `seq` | integer | order within the extraction; unique with `extraction_id` |
| `segment_type` | varchar(32) | `pdf_text_block`, `ocr_line`, `transcript_segment`, `table_header`, `table_row`, `email_header`, `email_body_text`, `email_body_html`, `email_attachment` |
| `text` | Text null | extracted text, untrusted |
| `data` | JSON null | cells, words, raw engine values, link list |
| `locator` | JSON | typed locator (section 6), source of truth |
| `page` | integer null | promoted from locator, indexed with `evidence_id` |
| `t_start`, `t_end` | float null | promoted from locator (seconds) |
| `engine_confidence` | float null | 0..1, engine-reported |
| `language` | varchar(16) null | |
| `created_at` | timestamptz | |

Indexes: `uq_segments_extraction_seq (extraction_id, seq)`, `ix_segments_evidence_page (evidence_id, page)`, `ix_segments_case (case_id)`. `seq` starts at 0.

JSON uses `sa.JSON().with_variant(postgresql.JSONB(), "postgresql")`, so one definition works on SQLite and Postgres.

### 5.4 Migration safety
- `0003` uses `batch_alter_table` (already enabled through `render_as_batch=True`) and only adds nullable or defaulted columns.
- `0004` only creates tables.
- Neither touches existing rows. Downgrades drop what they added.
- Before the first `alembic upgrade head` on the developer's real database (`backend/var/evidencex.db`, which now holds the four test cases and uploads), take a file copy as a backup. The spec never deletes or resets it.
- The migration test runs `upgrade head` on a fresh database and on a database seeded at revision `0002` with an evidence row, then checks the row survives.

## 6. Locators

Pydantic discriminated union on `kind`, validated on write and read:

```python
PdfLocator    {kind:"pdf",   page:int>=1, bbox:[x0,y0,x1,y1]|None, page_width, page_height, unit:"pt"}
ImageLocator  {kind:"image", bbox:[x0,y0,x1,y1], width:int, height:int, unit:"px"}
AudioLocator  {kind:"audio", start:float>=0, end:float>=start}
CsvLocator    {kind:"csv",   row:int>=1, line:int>=1, column:str|None}   # column null = whole row
XlsxLocator   {kind:"xlsx",  sheet:str, row:int>=1, range:str}          # e.g. "A12:F12"
EmailLocator  {kind:"email", part:"header"|"body_text"|"body_html"|"attachment",
               name:str|None, index:int|None}
```
`locators.py` exposes builders (`pdf_locator(...)`, ...) that return both the locator and the promoted values (`page`, `t_start`, `t_end`), so the two can never disagree. A unit test asserts that for every segment type.

## 7. API

All paths sit under the existing evidence router prefix, in a new router mounted in `main.py`. Path IDs are UUIDs. Every handler resolves evidence with `(case_id, evidence_id)`.

| Method and path | Purpose | Success |
|---|---|---|
| `POST /api/cases/{case_id}/evidence/{evidence_id}/process` | queue one item. Body `{ "force": false }` optional | 202 `ProcessAccepted` |
| `POST /api/cases/{case_id}/evidence/process-pending` | queue all `pending` items in the case | 202 `ProcessAccepted` |
| `POST /api/cases/{case_id}/evidence/{evidence_id}/retry` | queue a `failed` item | 202, or 409 if not failed |
| `GET /api/cases/{case_id}/evidence/{evidence_id}/processing` | status, error, attempts, timestamps, extraction summary | 200 |
| `GET /api/cases/{case_id}/evidence/{evidence_id}/extraction` | the current run: record, metadata, warnings | 200, or 404 if no current run |
| `GET /api/cases/{case_id}/evidence/{evidence_id}/extractions` | run history, newest first | 200 `ExtractionList` |
| `GET /api/cases/{case_id}/evidence/{evidence_id}/extractions/{extraction_id}` | one run | 200, or 404 |
| `GET /api/cases/{case_id}/evidence/{evidence_id}/segments?extraction_id=&page=&segment_type=&limit=&offset=` | paginated segments with locators. Defaults to the current run | 200 `SegmentList` |
| `GET /api/cases/{case_id}/processing` | counts per status plus per-item status, outcome, segment count | 200 |

`ProcessAccepted`: `{ queued: [uuid], skipped: [{evidence_id, reason}] }` with reasons `already_completed`, `already_processing`, `no_extractor`. Items with no extractor in the running build stay `pending`. Request-side checks are advisory; the atomic claim in the runner is the real guard.

`EvidenceOut` (existing) gains read-only fields `processing_started_at`, `processing_completed_at`, `processing_attempts`, `processing_error_code`. `EvidenceType` gains `tabular` and `email`. These are additive; existing clients keep working.

## 8. Extractor designs

### 8.1 PDF (`pdf.py`)
- `pymupdf.open(stream=data, filetype="pdf")` (import `pymupdf`, fall back to `fitz`).
- `needs_pass` -> `PasswordRequiredError`. Open failure or `FileDataError` -> `CorruptFileError`. `is_repaired` -> warning.
- Per page: `page.get_text("blocks", sort=True)`. Text blocks (type 0) become `pdf_text_block` segments with the block box. Per-page summary (size, characters, images) goes into metadata.
- Page with fewer than 10 non-whitespace characters and at least one image counts as a scanned page. All pages scanned -> `needs_ocr`. Some -> `partial`.
- Stops at `MAX_PDF_PAGES` or `MAX_EXTRACTED_CHARS` with a warning.
- No JavaScript execution, no link following. Metadata strings are stored as raw text.
- Optional later phase (decision D3): `PDF_OCR_FALLBACK=true` renders scanned pages and runs the image OCR path, tagged `ocr_line` with the PDF page locator.

### 8.2 Image OCR (`image_ocr.py`)
- Pillow: set `Image.MAX_IMAGE_PIXELS` from limits, `exif_transpose`, convert to RGB.
- `pytesseract.image_to_data(output_type=DICT, lang=..., timeout=OCR_TIMEOUT_SECONDS)`.
- **Pure function** `group_words_into_lines(data_dict, width, height)` groups words by `(block_num, par_num, line_num)`, drops confidence `-1` entries, builds the union box, mean confidence / 100. This function is unit-tested without Tesseract.
- Missing binary raises `DependencyMissingError("Tesseract not found. Install it and set TESSERACT_CMD ...")`.

### 8.3 Audio (`audio.py`)
- A `Transcriber` protocol (`transcribe(data) -> TranscriptionResult`) separates the engine from the extractor logic. The default implementation wraps `faster_whisper.WhisperModel`; tests inject a fake.
- Model loading: process-wide lazy singleton behind a lock. `local_files_only = not WHISPER_ALLOW_DOWNLOAD`. A missing local model raises `ModelUnavailableError` naming `python -m app.tools.fetch_whisper_model`.
- Decoding is done by PyAV inside faster-whisper, so system ffmpeg is not required (it is installed here anyway).
- `engine_confidence = clamp(exp(avg_logprob), 0, 1)`; raw values stay in `data`.
- Optional VAD filter (`WHISPER_VAD_FILTER`, default true). Word timestamps off by default.

### 8.4 CSV (`csv_extractor.py`)
- Decode with strict codecs in order `utf-8-sig`, `utf-16` (only with BOM), `cp1252` with a warning.
- Delimiter via `csv.Sniffer` on the first 64 KB restricted to `, ; tab |`.
- One `table_header` segment (row 1) plus one `table_row` segment per record. `csv.reader` runs with `strict=False`; `reader.line_num` gives the source line. Cell values are never altered.
- Type hints use regexes for integer, decimal, boolean and empty. Dates stay text.

### 8.5 XLSX (`xlsx.py`)
- `load_workbook(BytesIO(data), read_only=True, data_only=False)` for formulas and a second pass with `data_only=True` for cached values, zipped by coordinate.
- Coordinates computed with `get_column_letter`, since read-only empty cells carry no coordinate.
- Sheet state read from `ws.sheet_state`. Hidden sheets are extracted and flagged.
- `defusedxml` is a required dependency. A unit test asserts `openpyxl.xml.DEFUSEDXML is True`.
- Upload validation lists the ZIP (entry count, total uncompressed size, presence of `xl/workbook.xml`) before the file is stored.

### 8.6 EML (`eml.py`, `html_text.py`)
- `email.message_from_bytes(data, policy=email.policy.default)`.
- Header segments for the listed fields. Raw header strings kept; addresses parsed with `email.utils`. Dates use `email.utils.parsedate_to_datetime` only for the extra ISO field.
- Body parts via `walk()`, skipping attachments. Charset errors fall back to `replace` with a warning.
- `html_text.py`: a small `HTMLParser` subclass that skips `script`, `style`, `template`, `noscript`, inserts line breaks at block tags, and records `href` values. No network, no rendering.
- Attachments: name sanitized for display (control characters removed, length capped), MIME type, decoded size, SHA-256. Content is not stored.

## 9. Configuration (all in `Settings` and `.env.example`)
| Variable | Default | Purpose |
|---|---|---|
| `PROCESSING_MAX_CONCURRENCY` | 1 | simultaneous heavy extractions |
| `PROCESSING_STALE_MINUTES` | 30 | when `processing` becomes reclaimable |
| `PROCESSING_ISOLATION` | `inline` | `inline` or `subprocess` (subprocess is an optional phase) |
| `MAX_PDF_PAGES` | 500 | |
| `MAX_TABULAR_ROWS` | 50000 | rows across a CSV or workbook |
| `MAX_CELL_CHARS` | 32768 | per-cell cap |
| `MAX_EXTRACTED_CHARS` | 5000000 | per-file text cap |
| `MAX_IMAGE_PIXELS` | 50000000 | decode guard |
| `MAX_ZIP_ENTRIES` | 5000 | XLSX validation |
| `MAX_ZIP_UNCOMPRESSED_MB` | 250 | XLSX validation |
| `TESSERACT_CMD` | empty (use PATH) | full path to `tesseract.exe` |
| `TESSERACT_LANGS` | `eng` | OCR languages |
| `OCR_MIN_CONFIDENCE` | 0.40 | below this the outcome is `partial` |
| `OCR_TIMEOUT_SECONDS` | 120 | per image |
| `WHISPER_MODEL_SIZE` | `base` | `tiny`, `base`, `small`, ... |
| `WHISPER_MODEL_DIR` | `./var/models` | local model cache, outside web-served paths |
| `WHISPER_DEVICE` | `cpu` | |
| `WHISPER_COMPUTE_TYPE` | `int8` | |
| `WHISPER_LANGUAGE` | empty (auto-detect) | |
| `WHISPER_ALLOW_DOWNLOAD` | `false` | must be `true` before any download |
| `WHISPER_VAD_FILTER` | `true` | |
| `PDF_OCR_FALLBACK` | `false` | optional phase |

## 10. Frontend design

Existing `EvidenceSection` keeps upload and delete logic. It is split into smaller pieces; behavior of upload, download and delete does not change.

```
components/evidence/
  evidence-section.tsx          (existing) orchestrates; adds toolbar + polling
  evidence-row.tsx              (new) one row: icon, name, meta, status badge, actions
  processing-status-badge.tsx   (new) status + outcome presentation
  processing-toolbar.tsx        (new) "Process all pending (N)" + progress bar + counts
  extraction-viewer.tsx         (new) summary, warnings, metadata, segment list
  segment-item.tsx              (new) text + source reference + confidence
  source-reference.ts           (new) locator -> readable string (pure, typed)
hooks/use-processing-poll.ts    (new) polls /processing every 2 s while work is active
lib/api/processing.ts           (new) typed calls
lib/types/processing.ts         (new) types mirroring backend schemas
```

Interactions:
1. Click **Process** on a pending row -> `POST .../process` -> row shows "Queued" locally -> polling shows `processing` (spinner) -> `completed`.
2. **Process all pending (N)** -> one POST; the toolbar progress bar shows `completed / total`, with processing, pending and failed counts.
3. **Retry** on a failed row shows the error message and code (for example "Tesseract not found. Install ...") and re-queues on click.
4. **Re-process** on a completed row asks for confirmation ("This replaces the current extraction") and sends `force=true`.
5. **View extraction** expands an inline panel below the row: summary (extractor, version, outcome, time), warnings, metadata (collapsed), then segments with "Load more".
6. Source reference chips: `Page 3`, `00:01:12.3 - 00:01:18.9`, `Sheet "Payments" - C5`, `Row 14 - Amount`, `Header: Subject`, `Body (text)`, `Attachment 1`.
7. Notices: "Requires OCR" (`needs_ocr`) and "No extractable content" (`empty`) use a neutral style with an info icon, never the green success style.
8. All text is rendered as React text nodes inside `whitespace-pre-wrap`. Link targets are plain text.
9. Colors: green = completed, neutral slate = pending, processing, warnings. A new `failed` token (muted red) is used only for new failure states. Amber is untouched.

Frontend verification: `typecheck`, `lint`, `build`, plus a manual checklist (the repo has no frontend unit-test runner; adding one is out of scope for this stage).

## 11. Security design
- **Validation first**: signature plus deep content checks before storage; limits enforced before and during extraction.
- **No paths**: extractors get bytes only; storage keys never leave the server.
- **Untrusted text**: stored as data, rendered as text, never executed or passed to any interpreter. Hidden or instruction-like text is stored like any other text.
- **Parser safety**: PyMuPDF opens from memory and runs no JavaScript; openpyxl runs with defusedxml and no formula evaluation; EML HTML is converted with a non-rendering parser; ZIP listing is checked before parsing.
- **Logging**: ids, extractor, outcome, counts, durations. No extracted text, no bytes.
- **Error messages**: generic and free of paths and content.
- **Native crash risk**: MuPDF, Pillow, PyAV and Tesseract are native code parsing hostile files. `ExtractionExecutor` is the seam for a subprocess executor with a hard timeout (optional phase P7, decision D2).
- **Downloads** keep `attachment` + `nosniff` (Stage 2).
- **CSV formula injection**: values are shown as text. Any future export must escape leading `= + - @`.

## 12. Steering updates required (docs only, applied with this spec)
- `safety-and-provenance.md` invariant 2: add CSV (row and column), XLSX (sheet and cell) and EML (header or body part) locators.
- `architecture.md`: replace the three-module processing description with the extractor layout above, add `tabular` and `email` types, and state that background jobs use their own session and that claiming happens at execution time.
- `00-implementation-plan/plan.md`: point Stage 3 at this spec and rename it "Evidence Processing".

## 13. Windows prerequisites and install commands
Python 3.13.15, Node, and ffmpeg are present. Missing items:

```powershell
# 1. Python packages (inside backend\.venv); versions resolved by the dry run
cd backend
.\.venv\Scripts\python.exe -m pip install pymupdf pillow pytesseract openpyxl defusedxml
.\.venv\Scripts\python.exe -m pip install faster-whisper          # audio extra

# 2. Tesseract binary (not a pip package). Use the UB-Mannheim Windows build.
winget search tesseract                                           # confirm the exact id first
winget install --id UB-Mannheim.TesseractOCR -e                   # id to be confirmed by the search above
#    then set in backend\.env:
#    TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe

# 3. Whisper model: explicit download, run by you, never automatic
.\.venv\Scripts\python.exe -m app.tools.fetch_whisper_model --size base
```
Approximate model download sizes (verify at download time): `tiny` about 75 MB, `base` about 145 MB, `small` about 480 MB.
pyproject changes: core dependencies `pymupdf`, `pillow`, `pytesseract`, `openpyxl`, `defusedxml`; optional extra `audio = ["faster-whisper"]`; install with `pip install -e ".[dev,audio]"`.
Note: `pymupdf 2.1` pulls in `pymupdf4llm`, `pymupdf-layout`, `networkx`, `psutil`, `tabulate`. Pin and verify at implementation (decision D4).

## 14. Files to create or modify
**Create (backend)**: everything under `app/modules/processing/` and `app/tools/` listed in section 2; `alembic/versions/0003_*.py`, `0004_*.py`; tests listed in `testing.md`.
**Modify (backend, additive)**: `app/core/config.py` (settings), `app/core/database.py` (SQLite busy timeout and WAL), `app/main.py` (mount router), `alembic/env.py` (import models), `app/modules/evidence/models.py` (4 columns), `app/modules/evidence/schemas.py` (new fields and types), `app/modules/evidence/validation.py` (new extensions plus deep checks), `app/modules/evidence/service.py` (call deep check), `pyproject.toml`, `.env.example`, `tests/conftest.py` (session factory and registry overrides), `tests/unit/test_evidence_validation.py` (one assertion).
**Create (frontend)**: files in section 10. **Modify (frontend)**: `components/evidence/evidence-section.tsx`, `file-type-icon.tsx`, `lib/types/evidence.ts`, `lib/api/evidence.ts` (accepted extensions), `tailwind.config.ts` (failed token).
**Docs**: this folder, plus the three steering and plan edits in section 12.

## 15. Open decisions (recommendation first)
- **D1 PDF segmentation**: text blocks with boxes (recommended, enables later highlighting) versus page-level text only (simpler).
- **D2 Isolation**: build the executor seam now, ship `inline`; add `subprocess` in the optional hardening phase (recommended) versus build subprocess first.
- **D3 Scanned-PDF OCR**: mark `needs_ocr` now (required); add OCR fallback as an optional phase (recommended) or skip.
- **D4 PyMuPDF**: license is AGPL-3.0 or commercial, which matters if the app is ever offered as a network service without releasing source. Keep it as planned (recommended for the hackathon) and note the alternative. Pin the exact version at install.
- **D5 Failure color**: add a new muted-red token for new failure states (recommended) versus reusing amber for consistency with Stage 2.
- **D6 Real dataset**: use a few small files from the downloaded dataset as golden fixtures (needs the folder path) versus generated fixtures only.
