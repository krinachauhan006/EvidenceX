# Local processing worker (OCR, speech, video)

The Vercel backend cannot run OCR (Tesseract), speech recognition (faster-whisper) or
video decoding (PyAV). The processing worker runs those steps on a Windows computer
that can, against the **same** Supabase database and the **same** private evidence
bucket as the deployed site. Users keep using the website; the worker only processes.

It is not a second API server and there is no separate queue. Nothing is uploaded to
the computer from the website; the worker reads the stored files from the bucket.

## How it works

```
 Browser ──> Vercel frontend ──> Vercel backend ──┬──> Supabase PostgreSQL
                                                   └──> Supabase Storage (private bucket)
                                                              ▲
 Windows computer: python -m app.cli worker ───────────────────┘ (same database + bucket)
```

1. **Gate on Vercel.** With `EXTERNAL_WORKER_MIMES` set, the backend never queues
   images, audio or video. *Process* returns the skip reason `external_worker`; the item
   stays **pending** (never "failed"), and the evidence list shows **Awaiting worker**.
2. **Polling.** Each pass, the worker looks for (across all cases, oldest first):
   - **pending** images, audio and video;
   - items of those types that **failed with `dependency_missing`** (processed by the
     server before the gate was set) or **`interrupted`** (an OCR process was stopped,
     for example by Ctrl+C; the file itself was never judged);
   - items of those types stuck in **processing** longer than `PROCESSING_STALE_MINUTES`
     (for example after the worker was stopped mid-item);
   - **completed PDFs** whose current run could not OCR its scanned pages because OCR
     was unavailable on the server (`needs_ocr`, or `partial` with `pages_need_ocr`).
     These get one new run (it becomes current; the earlier run stays in the history),
     and only if this computer has the PDF extractor and Tesseract **with the language
     data named in `TESSERACT_LANGS`**. A re-run is attempted once: if it again could
     not OCR the pages, or failed (storage, timeout, OCR error), it is not repeated by
     later passes or later worker starts (the run history records the attempt). Only an
     interrupted re-run is tried again. A failed re-run leaves the PDF **completed**
     with its previous run current; the failed run is kept in the history.
3. **Claim.** Each item is claimed with the existing atomic claim (one conditional
   `UPDATE`). Only one process can win, so the worker and the website never process the
   same item at once. An item claimed elsewhere is simply skipped.
4. **Heartbeat.** While an item runs, the worker refreshes its `processing_started_at`
   every `--heartbeat-seconds` (default 60), so a long transcription is not treated as
   abandoned. The heartbeat only touches the item while it is still `processing` under
   the worker's own claim.
5. **Extraction and saving** use the existing runner, extractors, subprocess isolation
   and per-item timeout, and the existing repository methods: one transaction per run,
   extraction history kept, exactly one current run. No database connection or
   transaction is held while the extractor runs (the claim session is closed first; the
   result is saved in a new short transaction). Saving is conditional on the claim:
   if another process reclaimed the item in the meantime, this attempt saves nothing
   (reported as `superseded`) and never marks the newer attempt's item failed.
6. **Analysis.** After a pass, each case that has a current run of a worker file type
   (or a scanned PDF this worker OCR'd) newer than the case's latest analysis run is
   analysed once (rule-based). This is read from the database on every pass, so a
   worker stopped between processing and analysis catches up on its next start. Starting
   an analysis takes the case's row lock, so the worker and the website can never both
   start one for the same case; if one is already running, the worker tries again on
   the next pass (with `--once`, on the next worker run).
7. **Failures** affect only that item. An item the worker itself fails (for example
   because an engine is missing here too) is not retried by the same worker process, so
   a missing engine cannot create a loop of failed runs. Restart the worker, or use
   `--retry-failed`, after fixing the cause.

## 1. Vercel configuration (once)

Add this variable to the **backend** Vercel project (Settings → Environment Variables,
Production and Preview), then **redeploy the backend**:

```
EXTERNAL_WORKER_MIMES=image/png,image/jpeg,image/webp,audio/wav,audio/mpeg,audio/mp4,video/mp4,video/quicktime,video/webm
```

PDFs are deliberately **not** listed: the server extracts text-layer PDFs itself, and the
worker only re-runs scanned PDFs that the server could not OCR. Every other setting stays
as it is. A malformed value (for example `image png`) stops the backend at start-up with
an error naming `EXTERNAL_WORKER_MIMES`.

## 2. Windows requirements (verified on this project's development machine)

| Component | Needed for | Check |
|---|---|---|
| `D:\Projects\EvidenceX\backend\.venv` with the backend installed, including the `audio` extra (`pip install -e ".[audio]"`) | everything; PyAV and faster-whisper | `.venv\Scripts\python.exe -c "import av, faster_whisper"` |
| Tesseract OCR (`C:\Program Files\Tesseract-OCR\tesseract.exe`, with `eng` data) | images, scanned PDFs, video frame text | `& "C:\Program Files\Tesseract-OCR\tesseract.exe" --version` |
| A local speech model (default `base`) in `backend\var\models` | audio, video soundtrack | `.venv\Scripts\python.exe -m app.tools.fetch_whisper_model --size base` (one-time download; never automatic) |
| Network access to Supabase (session pooler, port 5432, and the S3 endpoint) | database and bucket | the dry run below |

The worker prints which engines it found at start-up (yes/NO only).

## 3. Environment variables (this PowerShell window only)

| Variable | Value |
|---|---|
| `DATABASE_URL` | Supabase **session pooler** URL, port **5432** (from Connect → Session pooler) |
| `DATABASE_TRANSACTION_POOLER` | `false` (correct for the session pooler) |
| `STORAGE_BACKEND` | `s3` |
| `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | the same values as the Vercel backend |
| `PROCESSING_ISOLATION` | `subprocess` (default; PDF and video get a hard timeout) |
| `TESSERACT_CMD` | `C:\Program Files\Tesseract-OCR\tesseract.exe` |
| `WHISPER_MODEL_SIZE` | `base` (or another model you downloaded) |
| `HF_HUB_OFFLINE` | `1` (never contact the model hub while processing) |
| `CLAIM_EXTRACTOR` | `rule_based` |
| `PROCESSING_STALE_MINUTES` | optional; keep it equal to the Vercel value (10 recommended) |

The worker refuses to start (exit code 2) if `DATABASE_URL` is PostgreSQL but storage is
local (it would find none of the files and mark real evidence failed), if S3 settings are
missing, or if `--heartbeat-seconds` is more than half of `PROCESSING_STALE_MINUTES`.

## 4. Secure PowerShell setup

Open a **new** PowerShell window (not one with another virtual environment activated).
Passwords and keys are typed at hidden prompts: they never appear in a command line, in
the PowerShell history or in a file.

```powershell
Set-Location D:\Projects\EvidenceX\backend
$py = "D:\Projects\EvidenceX\backend\.venv\Scripts\python.exe"
Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue

function Read-Secret([string]$Prompt) {
  $s = Read-Host $Prompt -AsSecureString
  $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
  try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}

# Database: Supabase session pooler (port 5432)
$poolerHost = Read-Host "Session pooler host (ends in pooler.supabase.com)"
$projectRef = Read-Host "Supabase project ref"
$pw = [uri]::EscapeDataString((Read-Secret "Database password"))
$env:DATABASE_URL = "postgresql://postgres.${projectRef}:${pw}@${poolerHost}:5432/postgres?sslmode=require"
Remove-Variable pw
$env:DATABASE_TRANSACTION_POOLER = "false"

# Storage: the deployment's private bucket
$env:STORAGE_BACKEND = "s3"
$env:S3_BUCKET = "evidence"
$env:S3_ENDPOINT_URL = Read-Host "S3 endpoint (https://<ref>.storage.supabase.co/storage/v1/s3)"
$env:S3_REGION = Read-Host "S3 region"
$env:S3_ACCESS_KEY_ID = Read-Secret "S3 access key id"
$env:S3_SECRET_ACCESS_KEY = Read-Secret "S3 secret access key"

# Local engines
$env:PROCESSING_ISOLATION = "subprocess"
$env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
$env:WHISPER_MODEL_SIZE = "base"
$env:HF_HUB_OFFLINE = "1"
$env:CLAIM_EXTRACTOR = "rule_based"
$env:PROCESSING_STALE_MINUTES = "10"
```

The S3 keys give full access to every bucket in the Supabase project. Use them only in
this window and only on a computer you control.

## 5. Run

**Dry run** (lists what would be processed; claims nothing, changes nothing, takes no lock):

```powershell
& $py -m app.cli worker --dry-run
```

**One pass** (processes everything eligible once, analyses the affected cases, exits):

```powershell
& $py -m app.cli worker --once
```

**Continuous** (polls every 30 seconds until stopped):

```powershell
& $py -m app.cli worker --poll-seconds 30
```

Other options: `--retry-failed` (also retry worker file types that failed for another
reason, for example after fixing a corrupt-file report by hand; missing-engine and
interrupted failures are always retried), `--no-scanned-pdfs`, `--no-analysis`,
`--heartbeat-seconds N`, `--lock-file PATH`.

Only one worker runs per computer: a second one exits with "another EvidenceX processing
worker is already running". The lock is released by Windows when the process ends, even
after a crash.

## 6. Stopping

- **Ctrl+C once:** the worker finishes the item it is processing, skips the rest of the
  pass, and exits with "Worker stopped." Analysis of that pass is deferred to the next
  start.
- **Ctrl+C twice:** exits immediately. The item in progress stays `processing`; after
  `PROCESSING_STALE_MINUTES` the next worker run picks it up again.
- Ctrl+C reaches every program in the console window. The worker's own PDF/video
  subprocess ignores it, but a Tesseract process running at that moment is cut off.
  That item is recorded as failed with the code `interrupted` (never as unsupported or
  corrupt), the website keeps showing **Awaiting worker**, and the next worker run
  retries it automatically. No `--retry-failed` or database edit is needed.

## 7. Verify from the deployed website

1. Upload a small PNG (or WAV) to a test case on the deployed site.
2. Press **Process all**: the response says the file is waiting for the processing
   worker, and its badge reads **Awaiting worker** (not Failed).
3. Run `worker --dry-run`: the file is listed as `pending`. Run `worker --once`: it prints
   `<name> [pending]: completed` and the analysis line.
4. **Refresh** the case page (the evidence list does not poll for the worker's results):
   the badge reads **Completed**; *View extraction* shows OCR lines or transcript
   segments; claims, the timeline and search include the new text.
5. Optional: Vercel → backend → Logs show no processing requests for that file, which
   confirms the backend did not claim it.

## 8. Clear the variables afterwards

```powershell
Remove-Item Env:DATABASE_URL, Env:DATABASE_TRANSACTION_POOLER, Env:STORAGE_BACKEND, `
  Env:S3_BUCKET, Env:S3_ENDPOINT_URL, Env:S3_REGION, Env:S3_ACCESS_KEY_ID, `
  Env:S3_SECRET_ACCESS_KEY -ErrorAction SilentlyContinue
Remove-Variable poolerHost, projectRef -ErrorAction SilentlyContinue
exit
```

Closing the window also discards them; nothing was written to disk.

## Limitations

- **Video previews:** the deployed site decodes frame previews (`/evidence/{id}/frame`)
  on request with PyAV, which Vercel does not have. After the worker processes a video,
  its transcript and frame text are available, but frame preview images still fail on the
  deployed site.
- **No live refresh:** the website does not poll for results produced by the worker;
  refresh the page.
- **Scanned PDFs** are re-run only when the server's run reported `ocr_unavailable`. A PDF
  processed with `PDF_OCR_FALLBACK=false`, or whose pages could not be read even with OCR,
  is not re-run automatically (use *Re-process* on the website for PDFs).
- **Scanned PDFs re-processed on the website** after an OCR re-run (so that two runs
  report `ocr_unavailable`) are not re-run by the worker again; use *Re-process* on a
  computer with OCR, or on the website once OCR is available there.
- **First start:** analysis is due for every case whose current image/audio/video run is
  newer than its latest analysis run, including cases processed before the worker
  existed. Run `--dry-run` first: it prints how many cases would be analysed. Use
  `--no-analysis` to skip analysis entirely.
- **Database timeouts:** the worker holds no transaction during extraction, so an
  `idle_in_transaction_session_timeout` cannot cut a long transcription off. Each save
  is still one transaction, which is larger for long recordings: if the database role
  has a `statement_timeout`, check (`show statement_timeout;` in the Supabase SQL editor)
  that it is longer than a save takes. This was not verified against Supabase.
- The worker must be running for images, audio and video to be processed at all.
