# EvidenceX features: a beginner's guide

This guide explains what every part of EvidenceX does, why it exists and how to use it.
It is written for someone who is new to EvidenceX and has no technical background.

Everything here was checked against the application code. Where a feature exists only
partly, needs extra setup, or does not exist, the guide says so.

**Contents**

1. [What is EvidenceX?](#1-what-is-evidencex)
2. [Accounts and signing in](#2-accounts-and-signing-in)
3. [The Investigations dashboard](#3-the-investigations-dashboard)
4. [Creating and managing an investigation](#4-creating-and-managing-an-investigation)
5. [Evidence upload and supported file types](#5-evidence-upload-and-supported-file-types)
6. [Processing: turning files into readable text](#6-processing-turning-files-into-readable-text)
7. [OCR: reading text in images and scans](#7-ocr-reading-text-in-images-and-scans)
8. [Audio transcription](#8-audio-transcription)
9. [Video processing](#9-video-processing)
10. [The evidence workspace: reviewing extracted text](#10-the-evidence-workspace-reviewing-extracted-text)
11. [Running the analysis](#11-running-the-analysis)
12. [Claims](#12-claims)
13. [Entities and possible duplicates](#13-entities-and-possible-duplicates)
14. [Events](#14-events)
15. [Timeline](#15-timeline)
16. [Potential inconsistencies (contradictions)](#16-potential-inconsistencies-contradictions)
17. [Alternative explanations](#17-alternative-explanations)
18. [Knowledge graph](#18-knowledge-graph)
19. [Search and Ask](#19-search-and-ask)
20. [Review queue](#20-review-queue)
21. [Case overview](#21-case-overview)
22. [Reports and exports](#22-reports-and-exports)
23. [Audit trail](#23-audit-trail)
24. [Members, roles and permissions](#24-members-roles-and-permissions)
25. [AI processing and privacy](#25-ai-processing-and-privacy)
26. [The current deployment and the processing worker](#26-the-current-deployment-and-the-processing-worker)
27. [All statuses explained](#27-all-statuses-explained)
28. [A complete example, start to finish](#28-a-complete-example-start-to-finish)
29. [Quick reference](#29-quick-reference)

---

## 1. What is EvidenceX?

**What is it?** EvidenceX is a website for organising and examining evidence in one
place. You put different kinds of files into one "investigation" (also called a
"case"): documents, photos, recordings, videos, e-mails and spreadsheets. EvidenceX reads
them and pulls out the statements they contain.

**Why is it useful?** In a real investigation, the facts are spread across many files in
many formats. Checking whether a receipt, a witness recording and a photo agree with each
other takes a long time. EvidenceX does the slow reading and comparing, and shows you
where accounts *appear* to disagree.

**What makes it different:**

- **Every result points back to its source.** A statement found in a PDF links to the
  exact page and box. One found in a recording links to the exact second. You can always
  check the original.
- **People decide.** EvidenceX suggests. A person confirms or rejects every suggestion,
  and every decision is recorded.
- **It is careful about what it claims.** It never says who is guilty, never says who is
  lying, and never says whether a file is genuine. A "possible inconsistency" means two
  sources seem to say different things. It does not mean anyone did anything wrong.

**Example:** A delivery receipt says a truck arrived at 10:30. A witness says it was
about 11:15. EvidenceX finds both statements, notices that they may describe the same
arrival, and asks a reviewer whether the times really conflict.

---

## 2. Accounts and signing in

**What is it?** Everyone needs an account. Your account is identified by your e-mail
address.

**How do I use it?**

1. On the start page, choose **Start an Investigation** or **Create account**.
2. Enter your name, e-mail address and a password.
   The password must be 8 to 256 characters long and must not start or end with a space.
3. Choose **Create account**. You are signed in straight away.
4. Next time, use **Sign in**.
5. To leave, choose **Sign out** at the bottom of the left-hand menu.

**What happens after?** You land on the Investigations dashboard. A new account sees no
cases. You only see cases that you created or that someone added you to.

**Limitations:**

- After too many failed sign-in attempts, sign-in is blocked for a while (by default 8
  failures, then 15 minutes).
- Sessions end after a set time (7 days by default). Then you sign in again.
- The operator can close registration. Then **Create account** does not work.
- There is no "forgot password" feature.

---

## 3. The Investigations dashboard

**What is it?** The first page after signing in, called **Investigations** in the menu.
It lists your cases and shows totals across all of them.

**What you see:**

| Part | What it shows |
|---|---|
| **Open cases** | How many of your cases are open (and how many are archived) |
| **Evidence items** | How many files are in all your cases together |
| **Claims to review** | Statements that nobody has decided on yet |
| **Possible inconsistencies** | Disagreements awaiting a review decision |
| **Filter by title or description** | Type words to narrow the list of cases |
| **Status buttons** | Show open cases, archived cases, or all |
| **Processing activity** | Files that are pending, processing or failed, in any of your cases |
| **Evidence by type** | How many PDFs, images, recordings and so on you have |
| **How a case flows** | A five-step reminder of the normal workflow |
| **New investigation** | Opens the form to create a case |
| **Explore Demo Investigation** | Loads a fictional example case (see below) |

**Why is it useful?** It tells you at a glance where work is waiting.

### The demo investigation

**What is it?** An optional, fictional example case called "Missing pallet shipment
(demo)". It contains six invented files: a delivery receipt (PDF), a gate log photo, a
dock camera video, a driver call recording, a pallet ledger (CSV) and a witness e-mail.
None of it is real evidence.

**How do I use it?** On the Investigations dashboard, find the **Explore Demo
Investigation** card (labelled **Fictional demo data**) and choose **Load demo case**.

**What happens after?**

- EvidenceX creates a private copy of the case for your account. You are its owner,
  and nobody else can see it unless you add them as members.
- You are taken straight to the case.
- The PDF, CSV and e-mail are processed by the website, and the case is analysed.
- The photo, video and recording show **Awaiting worker** until the local processing
  worker handles them. Refresh the page later to see their results.
- Choosing the card again (now **Open demo investigation**) opens the same case. It
  never creates a second copy. If an earlier load stopped part-way, the missing files
  are added.
- You can delete the demo case like any other case. Loading it again then creates a
  fresh copy.

---

## 4. Creating and managing an investigation

### Create a case

1. On the dashboard, choose **New investigation**.
2. Enter a **title** (required, up to 200 characters), for example "Missing pallet
   shipment".
3. Optionally add a **description**.
4. Choose **Create case**.

You become the case **owner**. Only you can see it until you add members (section 24).

### The case page

Each case has a header and a row of tabs.

**Header:**

| Element | Meaning |
|---|---|
| Case title and description | What you typed when creating the case |
| **open** / **archived** badge | The case status |
| Role badge (**owner**, **editor**, **reviewer**, **viewer**) | *Your* role on this case |
| **AI allowed** badge | Shown only if the owner allowed AI for this case (section 25) |
| **Run analysis** | Starts the analysis (section 11). Shown to editors and owners |
| Last run line | When the analysis last ran and which method it used |
| **Edit** | Change the title or description (editors and owners) |
| **Archive** / **Unarchive** | Move the case out of, or back into, the open list (editors and owners) |
| **Delete** | Permanently delete the case (owners only) |

**Tabs:** Overview, Evidence, Claims, Events, Timeline, Entities, Inconsistencies, Graph,
Search & ask, Review queue, Reports, Audit, Members & settings. Each is explained below.

### Archive and delete

- **Archive** keeps everything. It only hides the case from the "open" list. You can
  still open it and work in it, and **Unarchive** brings it back.
- **Delete** removes the case and *all* of its files, extracted text, claims, reports and
  review history. You must confirm it, and it cannot be undone.

---

## 5. Evidence upload and supported file types

**What is it?** The **Evidence** tab is where you add files to the case.

**How do I use it?**

1. Open the case and choose the **Evidence** tab.
2. Drag files onto the upload area, or choose **browse files**. You can add several at
   once.
3. Each file shows its own progress. A message confirms when it is uploaded.

**Supported file types:**

| Kind | File endings | What EvidenceX reads from it |
|---|---|---|
| Documents | `.pdf` | Text, with page and position |
| Images | `.png`, `.jpg`, `.jpeg`, `.webp` | Text in the image (OCR) |
| Audio | `.wav`, `.mp3`, `.m4a` | Spoken words (transcription), with times |
| Video | `.mp4`, `.mov`, `.webm` | Text on sampled frames, and the soundtrack |
| Spreadsheets | `.csv`, `.xlsx` | Rows and cells |
| E-mail | `.eml` | Headers (from, to, date, subject), body text, list of attachments |

**What happens after?** The file is checked and stored. Its status becomes **Pending**,
which means it is stored but not yet read. Uploading does *not* read the file.
Reading it is a separate step called processing (section 6).

**Safety checks you may notice:**

- EvidenceX looks at the file's actual content, not just its name. A text file renamed
  to `.pdf` is refused.
- Empty files are refused.
- Files are never run or opened as programs.
- Each file gets a **SHA-256 fingerprint**. This is a long code computed from the file's
  content. It changes if even one byte changes. It identifies the file. It does **not**
  prove that the file is genuine.

**Other buttons on each file:**

| Button | What it does |
|---|---|
| **Open workspace** | Opens the detailed view of this file (section 10) |
| **View extraction** / **View history** | Shows the extracted text, or past attempts, below the file |
| **Download** | Downloads the original file, unchanged |
| **Delete** | Deletes this file after you confirm (editors and owners) |

**Limitations:**

- On the current deployment, each file can be at most **4.5 MB**. This is a limit of the
  hosting platform (Vercel). A larger file is refused with a clear message. Uploading
  larger files directly to storage is not implemented.
- On a local installation the default limit is 25 MB (200 MB for video).
- Other formats (for example `.docx`, `.zip`, `.msg`) are not supported.

---

## 6. Processing: turning files into readable text

**What is it?** Processing means EvidenceX reads a file and turns it into small pieces of
text called **segments**. Each segment remembers exactly where it came from. For a PDF
that is a page and a box, for a recording a start and end time, for a spreadsheet a row
and column. This location is called the **locator**.

**Why is it useful?** Everything else in EvidenceX is built from these segments. Without
processing, there is nothing to analyse.

**How do I use it?** (editors and owners)

- **Process all pending (N)** at the top of the Evidence tab processes every pending file
  that this server can handle.
- **Process** on one file processes just that file.
- **Retry** appears on a failed file and tries again.
- **Re-process** appears on a completed file. It asks you to confirm, then creates a new
  extraction "run".
- The **refresh** button (circular arrows) reloads the status.

**What happens after?**

- The status changes to **Processing**, then to **Completed** or **Failed**.
- The processing bar shows completed, processing, pending and failed counts.
- While something is processing, the page updates itself every few seconds.

**Runs and history:** Each processing attempt is a **run** (run 1, run 2, …). Re-processing
never deletes older runs. The newest successful run is the **current** run, and that is
what the rest of EvidenceX uses. A failed run never replaces an earlier successful one.

**Results that are not plain success:**

| Label | Meaning |
|---|---|
| **Partial** | Some content was read, some could not be (see the warnings) |
| **Requires OCR** | A PDF has no text layer (it is a scan) and no OCR was available |
| **No content** | The file was read but contained nothing to extract |

**Why a file can fail** (the error shown under the file):

| Message | Plain meaning |
|---|---|
| Corrupt or unreadable file | The file is damaged or not what it claims to be |
| Password required | The file is password-protected |
| Unsupported content | The engine could not handle this content |
| Required component missing | The engine needed (OCR, speech, video) is not installed where processing ran |
| Model unavailable / Speech model damaged / Speech model failed to start | A problem with the speech-recognition model |
| Limit exceeded | The file is too large, too long or has too many pages |
| Timed out | Processing took too long and was stopped |
| Stored file missing | The stored copy of the file could not be found |
| Interrupted before finishing | The processing program was stopped (for example by Ctrl+C). The file was not judged; it can be processed again |
| Not enough memory | The computer ran out of memory |
| Internal error | An unexpected problem, including the storage service being unreachable |

**Limitations:** On the current deployment, images, audio and video are processed by a
separate computer, not by the website. See section 26.

---

## 7. OCR: reading text in images and scans

**What is it?** OCR (optical character recognition) means reading written or printed text
from a picture. EvidenceX uses a program called **Tesseract** for this.

**Where it is used:**

- **Photos and scans** (`.png`, `.jpg`, `.webp`): each line of text becomes a segment with
  the pixel area it came from.
- **Scanned PDF pages** (pages with no text layer): the page is turned into an image and
  read.
- **Video frames**: text visible on sampled frames is read.

EvidenceX straightens tilted images and corrects their orientation before reading them.

**Example:** A photo of a gate log reads "Truck KX-4471 arrived 10:34". OCR turns that
into a text segment. The workspace draws a box around the line on the photo.

**What the numbers mean:** Each OCR line has an **engine confidence**. This is
Tesseract's own guess of how well it read the text. It is *not* a measure of whether the
text is true.

**OCR languages (Members & settings tab):**

- If the server has Tesseract, this card lists its installed languages and the default.
- On the current deployment, the website's server has no Tesseract. The card then says
  that OCR is handled by the local processing worker, using the languages installed on
  that computer.
- Older versions of this page showed "Tesseract OCR was not found on this server." That
  message described only the website's server. It did not mean OCR was unavailable
  overall.

**Limitations:**

- OCR quality depends on the picture. Blurry or handwritten text may be misread.
  Low-confidence results are kept and marked, never "improved".
- The API can accept a different OCR language for a single file, but the website has no
  control for this. The worker always uses the language set on its own computer.

---

## 8. Audio transcription

**What is it?** Transcription turns spoken words in a recording into written text.
EvidenceX uses **faster-whisper**, a speech-recognition model that runs on the computer
doing the processing. Recordings are not sent to an online service.

**What you get:**

- Each spoken passage becomes a **transcript segment** with a start and end time.
- Individual words keep their own times. Words the engine was unsure about are marked
  "possibly misheard" (dashed underline).
- Every transcript is labelled as machine output and **Unreviewed** until a person
  corrects it.

**How do I use it?**

1. Open the recording's workspace (Evidence → **Open workspace**).
2. On the **Original preview** tab, play the recording. Choose a segment to jump to that
   moment.
3. If a passage is wrong, choose **Correct transcript**, type the right text, optionally
   add a note, and choose **Save correction**.

**What happens after a correction?** The original machine text is kept unchanged. The
correction is stored separately with your name and the time, and the segment shows
**Corrected by …**. The correction appears in the audit trail as "Transcript corrected".

**Example:** The transcript reads "the truck came at eleven fifteen". You listen and
confirm it. Or, if it actually said "eleven fifty", you save a correction.

**Limitations:**

- The speech model is never downloaded automatically. It must be installed on the
  processing computer once.
- Recordings longer than 20 minutes are refused by default.
- The workspace has a **speech model** dropdown for the next run. It only affects
  processing done by the website's server, and on the current deployment that server has
  no model. It may show "The default speech model is not on disk". That is true for the
  website's server only; the processing worker uses its own model.

---

## 9. Video processing

**What is it?** EvidenceX does not watch the whole video. It takes **sampled frames**:
one every 10 seconds by default, plus frames where the scene changes, up to 60 frames.
For each frame it:

- records the time;
- reads any visible text with OCR;
- transcribes the soundtrack the same way as an audio file.

**Why is it useful?** It finds things like a number plate, a timestamp overlay or a sign
in the video, and what was said, each with the moment it happened.

**How do I use it?** Open the video's workspace. You can play the original video, see a
timeline of sampled frames and speech, read the text found on frames, and read the
soundtrack transcript.

**Limitations:**

- Moments between sampled frames are not examined.
- There is no face recognition and no authenticity analysis.
- Videos longer than 30 minutes are refused by default.
- **Frame preview images do not work on the deployed website.** Showing a single frame
  as a picture needs a video library (PyAV) that the website's server does not have.
  The extracted text and transcript still appear once the worker has processed the video.
  Playing the original video in the browser uses the downloaded file and does not need
  that library.

---

## 10. The evidence workspace: reviewing extracted text

**What is it?** A detailed page for one file. Open it with **Open workspace** on the
Evidence tab, or by following any **Open source** / **Show in source** link.

**Header:** file name, status, type, size, upload time, current run, engine and model,
processing time, and the SHA-256 fingerprint (with a copy button). The buttons are:

- **Process** / **Retry** / **Reprocess (new run)**: same as on the Evidence tab.
- **Download original**: downloads the file unchanged.
- **History**: opens the run history.

There is also a row of counts: segments, claims, entities, relationships, potential
inconsistencies, and items awaiting review.

**Tabs:**

| Tab | What it shows |
|---|---|
| **Overview** | The three layers (original file, extracted content, machine claims), extraction warnings and the most important claims |
| **Original preview** | The file itself: PDF pages, the image, the audio or video player, the e-mail, or the table. Boxes and highlights show where segments came from |
| **Extracted content** | Every segment, with its locator. This text is never edited |
| **Claims** | Claims taken from this file |
| **Entities** | Entities mentioned in this file and how they were written |
| **Relationships** | Links between this file's claims and claims in other files, for example "potentially conflicts with" |
| **Processing details** | The current run: extractor, outcome, timing, warnings, speech settings, all metadata |
| **Run history** | Every run, successful or failed. Runs are never deleted |

**Why is it useful?** It is the place to check a result against the original. When a
claim says "10:30", you can see the exact box on the receipt it came from.

**Important:** Extracted text is treated as *untrusted data*. If a document contains text
such as "ignore previous instructions", EvidenceX stores it as content. It never follows
it as a command.

---

## 11. Running the analysis

**What is it?** **Run analysis** (in the case header) reads the processed segments of
*all* files in the case and produces:

- **claims** (statements);
- **entities** (identifiers, vehicles, places, contacts);
- **event proposals** (groups of claims that may describe one occurrence);
- **relationships** and **potential inconsistencies**.

**How do I use it?** (editors and owners)

1. Process the evidence first.
2. Choose **Run analysis**. The button changes to **Analysing…** with a progress bar.
3. When it finishes, a message says "Analysis finished", and all tabs refresh.

**What happens after?** The header shows "Last run … · Rule-based extraction (not AI)"
(or AI-assisted, if AI is enabled). If some files could not be analysed, it says how
many.

**Good to know:**

- You can run it again after adding or re-processing files. Claims you already reviewed
  are kept.
- Only one analysis can run per case at a time. A second start is refused while one is
  running.
- Viewers and reviewers cannot start it, but they see "Analysis in progress".
- On the current deployment, the processing worker also starts an analysis by itself
  after it finishes files in a case.

**Empty results are worded carefully.** Before any analysis, a page says "This case has
not been analysed yet". After an analysis that found nothing, it says "The latest
analysis found no …", followed by an explanation that this does *not* mean the evidence
contains none.

---

## 12. Claims

**What is it?** A **claim** is a statement found in the evidence that can be checked.
Examples: "Truck KX-4471 arrived at 10:30", "Invoice total 4,200", "Delivered to
Warehouse A".

**How claims are found:** By default, fixed rules look for times, dates, quantities,
identifiers (such as shipment or invoice numbers), places and record values. AI can be
used instead, but only when it is set up and allowed (section 25).

**What a claim card shows:**

| Part | Meaning |
|---|---|
| Status badge | Unreviewed, Needs verification, Verified by reviewer, Rejected by reviewer |
| Type | date / time, quantity, location, identity, record or statement |
| Source kind | pdf, image, audio, table, e-mail and so on |
| **Machine interpretation** | What the rules (or AI) understood |
| **Reviewer's interpretation** | A person's corrected wording, if one was saved |
| **Exact source quote** | The words exactly as they appear in the file, with their location |
| Time as written | The time, keeping its precision ("about 11", a range, or ambiguous) |
| Engine confidence | How sure the OCR or speech engine was about the text |
| Extraction confidence | "Not applicable (rule-based)", or the AI's self-assessment |
| Entity chips | Entities this claim mentions; click to open them |
| Amber "potential inconsistency" badge | This claim is part of a disagreement awaiting review |
| "Source match insufficient" | The quote could not be matched to the source text |
| "From earlier run N" | The file was re-processed after this claim was made |
| "Inferred, not stated" | The statement is a deduction, not a direct quote |

**Buttons (reviewers and above):**

| Button | Effect |
|---|---|
| **Show in source** | Opens the file at the exact place the quote came from |
| **Verify** | You checked it against the source and it says this |
| **Needs verification** | It needs further checking |
| **Reject** | The claim is wrong or not useful |
| **Edit interpretation / note** | Save your own wording, or add a note. The machine text and quote stay unchanged |

**Filters on the Claims tab:** search text, review status, claim type, source kind, and
**Include claims from earlier runs**.

**Important:** A claim records *what a source says*. It is not treated as true until a
reviewer verifies it. Even then, "verified" means "the source really says this", not
"this really happened".

**Limitations:** The rules find explicit times, dates, quantities, identifiers and
places. They do not understand free-flowing narrative, and they do not extract names of
people or organisations from ordinary sentences.

---

## 13. Entities and possible duplicates

**What is it?** An **entity** is a specific, identifiable thing mentioned in the
evidence. In EvidenceX the types are: identifiers (such as shipment or invoice numbers),
shipments, vehicles (number plates), locations, and contacts (e-mail addresses).

**Why is it useful?** It connects files. If the receipt, the gate photo and the e-mail
all mention shipment NS-88421, they are linked through that entity.

**How entities are matched:** Only values that are identical after normalising share
one entity. For example, "NS-88421" and "NS88421" are the same. Values that are only
*similar* are listed as **possible duplicates** and are never merged automatically.

**The Entities tab:**

- **Left side:** search box, type filter, the list of entities (with file count "f" and
  mention count "m"), and **Possible duplicates**.
- **Right side:** the selected entity: its normalised key, how it was written ("Written
  as"), every mention with its quote and **Open source**, and its review history.

**Entity buttons** (reviewers and above):

| Button | Effect |
|---|---|
| **Confirm entity** | This is a real, correctly identified entity |
| **Reject (not a real entity)** | The rules picked up something that is not a real entity |
| **Unmerge** | Undo an earlier merge |
| **Add note** | Record a remark |

**Possible duplicates:** Pairs are ranked in tiers:

| Tier | Meaning |
|---|---|
| **Exact** | Identical characters, recorded under different identifier types |
| **Strong** | The same digits, with a prefix missing on one side |
| **Weak** | One digit differs; often two different records |
| **Conflicting** | Signals point both ways, for example the same name with different e-mail addresses |

The score next to the tier is only for ordering the list. It is not a probability. For
each pair, choose:

- **Same entity: merge**: combines them. The original mentions are kept unchanged.
- **Different entities**: records that they are not the same.
- **Decide later**: defers the decision with a note on what would settle it.

---

## 14. Events

**What is it?** An **event** is a proposed grouping of claims that may describe the same
real-world occurrence. Example: three files all describe "the delivery of shipment
NS-88421".

**How events are proposed:** The rules group claims of the same kind that share an
**anchor**: a shared identifier, a shared number plate, a shared named place, or only the
same object word (the weakest anchor). Each event has an **association score**. It is a
rough ordering aid, not a probability that the event happened.

**Why it matters:** EvidenceX compares the times in accounts only *after* a reviewer
confirms that they describe one occurrence. This prevents false alarms between accounts
that are actually about different things.

**The Events tab:**

- Counts: **Proposed** (awaiting a reviewer), **Confirmed**, **Rejected**, and **Pairs
  that differ**.
- Filter tabs: Proposed, Confirmed, Rejected, All.
- **Re-run proposals** (editors and owners): asks the rules to propose again. Existing
  decisions are kept.

**An event card shows:**

- the title and status, and who proposed it ("proposed by the rules" or "grouped by a
  reviewer");
- a small time bar with each account's stated time;
- **Accounts**: each claim, its quote, why it was included, and **Open source**;
- **How the accounts compare**: each pair of accounts is labelled:

  | Label | Meaning |
  |---|---|
  | Times appear to conflict | Further apart than the tolerance; a possible inconsistency for review |
  | Possible time-zone difference | About a whole number of hours apart, with no time zone stated |
  | Possible rounding | A small difference where one time is approximate |
  | Within tolerance | Close enough to count as agreeing |
  | Approximate times overlap | At least one time is a range, and the ranges overlap |
  | Time missing | One account gives no time; missing information, not a disagreement |
  | Different days | The dates differ; times are not compared across days |
  | Same account | Both statements come from one source, so they are not independent |

- **Association score factors** and **Missing links**;
- a link to any potential inconsistencies that came from this event.

**Buttons** (reviewers and above):

| Button | Effect |
|---|---|
| **Same occurrence: confirm** | Confirms the grouping. The accounts are now compared |
| **Different occurrences: reject** | They are not one occurrence |
| **Not part of this event** | Removes one account (only on proposed events with more than two accounts) |
| **Reopen** | Puts a confirmed or rejected event back to proposed |
| **Add note** | Records your reasoning |

**Example:** The event "Arrival of KX-4471" groups the receipt (10:30) and the witness
statement (about 11:15). You confirm it. Their times are then compared, and a potential
inconsistency appears for review.

**Limitations:** The API can also create an event by hand, split an event, or add a
claim to an event. The website has no buttons for these yet. Events are proposed only by
rules, never by AI.

---

## 15. Timeline

**What is it?** Every claim with a time or date, in order, grouped by day.

**Why is it useful?** It shows what happened when, across all files, in one view.

**How do I use it?**

- Filter by source kind, review status or file.
- Each day has a bar of dots (colour = source kind). A dot with an amber ring is part of
  a possible inconsistency.
- Below the bar, each entry shows the time as written, the file, the quote, links to its
  events and inconsistencies, and an **Open source** link.

**Precision is kept:** A date taken from elsewhere in the same document is marked **date
inherited**. A date taken from an e-mail header is marked as such. Claims with no date are
listed separately under "Date not stated" and are not placed on a day.

---

## 16. Potential inconsistencies (contradictions)

**What is it?** A **potential inconsistency** (the code calls it a "contradiction") is a
pair of claims that appear to disagree. They are found in two ways:

- both claims mention the same identifier and disagree; or
- a reviewer confirmed that the claims describe one event, and their times conflict.

The kinds compared are **temporal** (times), **quantity** (amounts) and **sequence** (order
of steps). Location conflicts are not checked.

**Why is it useful?** These are leads for a person to examine. They are not findings. A
difference can be harmless, and EvidenceX never decides which source is correct.

**The Inconsistencies tab** lists them, with filters for review status and severity.
Opening one shows:

| Part | Meaning |
|---|---|
| **First source states / Second source states** | Both claims, their quotes, times as written and **Open source** |
| **Why they may be inconsistent** | The reason the rule flagged them |
| **What is uncertain** | What the rule could not know |
| **What would resolve it** | What evidence would settle it |
| **Severity** (low, medium, high) | The size of the difference, for example minutes apart. Not importance and not truth |
| **Detection confidence** | How cleanly the rule matched. Not the chance that a source is wrong |
| Factor list | What raised or lowered the detection confidence |
| "via confirmed event" | Found because a reviewer confirmed the event |
| "Based on an earlier run" | A source was re-processed after detection |
| **Alternative explanations** | Harmless reasons the difference may exist (section 17) |

**Review buttons** (reviewers and above):

| Button | Effect |
|---|---|
| **Confirm inconsistency** | You agree that the sources disagree. This does not say which one is right, and it is not a finding about anyone's conduct |
| **Mark unresolved** | It needs more work |
| **Resolve** | You explained the difference. A note is required |
| **Reject** | Not really an inconsistency |
| **Add note** | Record a remark |
| **History** | Show every decision made on it |

---

## 17. Alternative explanations

**What is it?** Every potential inconsistency comes with one or more **alternative
explanations**: harmless reasons the sources might differ. Examples: rounding ("about
11"), a clock set to a different time, two separate visits, a time-zone difference.

**Labels:**

- **Machine hypothesis (not source-supported)**: suggested by the rules as something to
  check.
- **Source-supported**: backed by something in the evidence.
- **Added by a reviewer**: written by a person.

Each may also list supporting evidence, what would weaken it, what is missing, and how to
verify it.

**How do I add one?** (reviewers and above) Open the inconsistency, type in **Add an
alternative explanation…**, and choose **Add**. It is saved with your name and appears in
the audit trail.

**Why is it useful?** It prevents a disagreement from being read as wrongdoing. The
reviewer is reminded of the innocent explanations before deciding.

---

## 18. Knowledge graph

**What is it?** The **Graph** tab draws the case as a network: files, the claims taken
from them, the entities those claims mention, events, and potential inconsistencies.
Every line comes from a stored record.

**How do I use it?**

- Hover over or select a dot to highlight its connections.
- Options: **Show claims**, **Only claims in potential inconsistencies**, an entity-type
  filter and a file filter.
- Export the graph as **JSON** or **GraphML**, using the current filters.

**Why is it useful?** It shows at a glance which files are connected and through what.

**Limitations:** The graph shows at most 250 nodes at a time.

---

## 19. Search and Ask

### Search the case

**What is it?** A search across all extracted text, claims, entities and events in the
case.

**How do I use it?** Type words, names or numbers (for example "KX-4471" or "invoice")
and choose **Search**. Use **Look in** to limit the search to source text, claims,
entities or events.

**What happens after?** Results show where they came from and why they matched, with the
matching words highlighted and an **Open source** link. The search tolerates small typos
and understands word forms ("arrive", "arrived") and a small list of synonyms. It runs
inside EvidenceX and uses no outside service.

### Ask a question

**What is it?** You ask a question in plain words, such as "When did the truck arrive at
Warehouse A?". The answer uses only passages from this case and cites them.

**There are two modes:**

- **Source passages only (no AI)**: the default on the current deployment. EvidenceX
  shows the most relevant passages word for word, with their sources. It does not write a
  summary.
- **AI answers with citations**: only when an AI key is configured *and* the owner
  allowed AI for this case. Any statement without a valid citation is removed before you
  see it.

Each answer statement is marked **supported**, **interpretation** or **unknown**, and
links to the cited sources listed below it. Any member, including a viewer, can ask.

---

## 20. Review queue

**What is it?** One list of everything waiting for a human decision, most important
first: potential inconsistencies, then claims involved in them, claims marked as needing
verification, and claims from machine transcription or OCR. It also lists possible
duplicate entities, with a link to decide them on the Entities tab.

**Why is it useful?** It is the reviewer's to-do list.

**Note:** An empty queue after an analysis means every item has a decision. It does not
mean the evidence has been verified.

---

## 21. Case overview

**What is it?** The **Overview** tab of a case. It shows counts (evidence, segments,
claims, entities, potential inconsistencies, review queue), breakdowns by type and
status, the entities seen in the most files, and recent review activity.

If potential inconsistencies await review, an amber banner links to them.

Counts are never shown as "all clear". Before the first analysis they show "—" and "not
analysed yet".

---

## 22. Reports and exports

**What is it?** The **Reports** tab produces PDF reports and graph files.

| Option | What you get | Who can use it |
|---|---|---|
| **Investigation report → Generate PDF** | Summary, scope, methods and limits, events and timeline, possible inconsistencies with their alternatives, gaps, and the review trail | Reviewers and above |
| **Knowledge-graph report → Generate PDF** | The graph drawn as a page, with a legend and a list of its nodes and links | Reviewers and above |
| **Graph as JSON → Download JSON** | The graph data for scripts and other tools | Everyone |
| **Graph as GraphML → Download GraphML** | Opens in graph tools such as Gephi, yEd or Cytoscape | Everyone |

**What happens after generating?** The report is stored with a **version number** (v1,
v2, …) and a **SHA-256 hash**. Older versions are kept. The list shows each report's
date, author, size and hash, with **Preview** and **PDF** (download) buttons.

The hash identifies that exact file. Anyone can recompute it later to check that the
download was not altered. It says nothing about whether the evidence is accurate.

**Limitations:**

- Reports describe what the sources say and where they appear to differ. They do not
  determine guilt, deception or authenticity.
- The backend can add an AI-drafted summary to the investigation report, but the website
  has no option to request it. Reports from the website use the rule-based summary.
- Viewers can preview and download existing reports but cannot generate new ones.

---

## 23. Audit trail

**What is it?** The **Audit** tab records every review decision, membership change,
consent change, transcript correction and report creation. Each record shows when it
happened, the action, what it was about, the status change, who did it (the signed-in
account) and any note.

**The chain check:** Each record contains a fingerprint (hash) of the record before it.
If anyone later edits or deletes a record, the chain breaks. The top of the page shows
**Audit chain intact** or **Audit chain broken**.

**Buttons and options:**

- **Verify again**: re-checks the chain now.
- **Record type** filter: claims, contradictions, entities, events, relationships,
  segments, case, case members.
- **head …**: the fingerprint of the newest record. Note it down to check later that
  nothing has changed since.

Records made before chaining was introduced are kept but listed as not chained.

---

## 24. Members, roles and permissions

**What is it?** The **Members & settings** tab controls who can see and change the case.
People who are not members cannot even tell that the case exists. The server checks
access on every request, so hiding a button is not the only protection.

### The four roles

Each role includes everything the role above it can do.

| Role | What it can do |
|---|---|
| **Viewer** | Read everything in the case; search and ask questions; preview and download existing reports; export the graph (JSON, GraphML); download evidence files |
| **Reviewer** | Everything a viewer can do, plus: verify, reject or edit claims; decide on inconsistencies and add alternative explanations; confirm, reject or reopen events; merge or separate entities; correct transcripts; generate reports |
| **Editor** | Everything a reviewer can do, plus: upload, process, re-process and delete evidence; run the analysis; re-run event proposals; edit, archive and unarchive the case |
| **Owner** | Everything an editor can do, plus: add, change and remove members; turn AI processing on or off; delete the case |

The person who creates a case is its owner.

### Managing members (owners only)

1. In **Members & settings**, type the person's e-mail. They must **already have an
   account**.
2. Choose a role and select **Add member**.
3. To change a role, use the dropdown next to the member. To remove someone, use the bin
   button.

Every change is recorded in the audit trail. Members who are not owners see the list,
but cannot change it.

**Example:** You own a case. You add a colleague as **reviewer**, so they can confirm
events and decide on inconsistencies but cannot delete files. You add a supervisor as
**viewer**, so they can read and download reports only.

**Permissions, privacy and availability are separate things:**

- A **permission** decides who may do something (for example, only owners change AI
  consent).
- A **privacy control** decides what may leave EvidenceX (the AI consent switch).
- **Technical availability** decides whether something can work at all (for example, AI
  needs a key, and OCR needs Tesseract).

A feature may be permitted for you and still unavailable on the current deployment.

---

## 25. AI processing and privacy

**What is it?** EvidenceX can optionally use an external AI service (Google Gemini) for
three things:

- claim extraction;
- answers to "Ask" questions;
- an AI-drafted summary in the investigation report.

Entity matching, event proposals and inconsistency detection never use AI.

**AI runs only when both of these are true:**

1. The server operator configured an AI key and an AI mode.
2. The case **owner** turned on **Allow AI processing** for that case.

### The AI processing card (Members & settings)

| Item | Meaning |
|---|---|
| **allowed** / **off** badge | The owner's decision for this case |
| Mode on this server | `rule_based` (no AI), `gemini` or `hybrid` |
| Model | The AI model that would be used |
| API key configured | "yes", or "no (AI cannot run even if allowed)" |
| **Allow AI processing** switch | Owners only. Records the decision in the audit trail |

### What is sent to the AI provider when AI is used

Only the **extracted text segments** of that case (with their internal ids), clearly
marked as data. EvidenceX never sends:

- the original files;
- file names;
- other cases;
- passwords, keys or account details.

AI output is checked against a fixed format before it is used, and it is labelled as AI
in the website and in reports.

### When AI is not available or not allowed

This is the situation on the current deployment unless a key has been added.

- Claims are extracted by rules. The header says "Rule-based extraction (not AI)".
- "Ask" shows the most relevant source passages word for word, and says why AI is not
  used (no key, or not allowed).
- Reports use the rule-based summary.

Everything else works the same: processing, claims, entities, events, timeline,
inconsistencies, graph, search, review, reports and audit. Turning consent off stops
future AI use. It does not delete results AI already produced; those stay labelled as AI.

**Limitations:** The AI features are implemented and tested with a simulated model only.
They have not been tested against the live Gemini service.

---

## 26. The current deployment and the processing worker

### How the current deployment is set up

| Part | Where it runs |
|---|---|
| Website (what you see) | Vercel |
| Backend (the server that answers the website) | Vercel |
| Database (cases, claims, decisions) | Supabase PostgreSQL |
| Evidence files | Supabase storage (a private, S3-compatible bucket) |
| Processing worker (OCR, speech, video) | A Windows computer running Python, with Tesseract, faster-whisper and PyAV installed |

### What happens where

| Task | Where |
|---|---|
| Accounts, cases, members, roles | Website |
| Upload, download, delete files (up to 4.5 MB each) | Website |
| PDF text extraction and PDF page previews | Website |
| Spreadsheet (CSV, XLSX) and e-mail (EML) extraction | Website |
| Analysis, claims, entities, events, timeline, inconsistencies, graph, search, Ask | Website (the worker can also start an analysis) |
| Reports and graph exports | Website |
| **Image OCR** | **Worker only** |
| **OCR of scanned PDF pages** | **Worker only** |
| **Audio transcription** | **Worker only** |
| **Video frames, frame text and soundtrack** | **Worker only** |
| Video frame preview pictures | **Not available** on the website (see section 9) |

### Why some files show "Awaiting worker"

The backend is told which file types the worker handles. For those types (images, audio
and video), the website does not try to process them, because it would fail. Instead:

- the file stays **Pending**, and its badge reads **Awaiting worker**;
- a note says "Waiting for the processing worker";
- the **Process**, **Retry** and **Re-process** buttons are hidden for these files.

When the worker is running, it finds these files by itself, processes them, saves the
results to the same database and storage, and then analyses the affected cases. If the
worker is not running, these files simply wait. Nothing is lost.

A file of these types that failed earlier because an engine was missing, or because
processing was interrupted, also shows **Awaiting worker**. The worker retries those by
itself.

### What the worker does automatically

- Processes pending images, audio and video.
- Retries files that failed only because an engine was missing or because processing was
  interrupted.
- Picks up files stuck in "processing" for too long (for example after the worker was
  stopped).
- Re-reads scanned PDFs once, if the website could not OCR their pages.
- Runs the analysis for cases with newly processed files.

Files that failed for other reasons (for example a corrupt file, or a storage error) are
**not** retried automatically. The worker operator can retry them with the worker's
`--retry-failed` option. There is no Retry button on the website for these file types.
See [PROCESSING_WORKER.md](PROCESSING_WORKER.md) for operator instructions.

### Why the OCR languages card mentions the worker

The OCR languages card reports on the website's own server, which has no Tesseract. OCR
does work, on the worker computer. The card now says so. An older version of the page
showed the misleading message "Tesseract OCR was not found on this server."

### Seeing the worker's results

While a file is being processed, the Evidence list and the workspace update themselves.
When the worker finishes a file while you are not watching, the page may not change by
itself. **Refresh the page** to see the results.

### Other deployment limits

- 4.5 MB per uploaded file.
- No AI unless an AI key is configured and the owner allows it.
- A processing task on the website that takes longer than 300 seconds is cut off. It is
  marked as stale later, and can then be retried.

---

## 27. All statuses explained

Only statuses that exist in the code are listed. There is no separate "Uploaded" status
(an uploaded file is **Pending**) and no "Analysis pending" status (a case that was never
analysed is shown as "not analysed yet").

### Evidence processing (badge on each file)

| Badge | Meaning |
|---|---|
| **Pending** | Stored, not processed yet |
| **Queued** | You asked to process it, and it has not started yet (shown briefly) |
| **Awaiting worker** | Waiting for the local processing worker (images, audio and video on the current deployment). Not a failure |
| **Processing** | Being read right now |
| **Completed** | Read successfully |
| **Partial** (next to Completed) | Some content could not be read; see the warnings |
| **Requires OCR** | A scanned PDF with no readable text layer, and no OCR was available |
| **No content** | Read, but nothing could be extracted |
| **Failed** | The last attempt failed; the reason is shown below the file |
| **Not available yet** | No extractor exists for this file type |

The underlying stored statuses are only four: `pending`, `processing`, `completed` and
`failed`.

### Extraction runs

| Status | Meaning |
|---|---|
| `completed` / `failed` | Whether that run succeeded |
| **current** | The run the rest of EvidenceX uses |
| Outcome `ok` / `partial` / `needs_ocr` / `empty` | Complete, Partial, Requires OCR, No extractable content |

### Analysis run (case header)

| State | Meaning |
|---|---|
| never analysed | No analysis has run ("This case has not been analysed yet") |
| running | "Analysing…" or "Analysis in progress" |
| completed | Finished; "Last run …" is shown |
| failed | "· failed" in the header; results may be incomplete |

### Claims

Unreviewed · Needs verification · Verified by reviewer · Rejected by reviewer

### Potential inconsistencies

| Label | Meaning |
|---|---|
| Awaiting review | No decision yet |
| Unresolved | Looked at, needs more work |
| Inconsistency confirmed | A reviewer agrees that the sources disagree |
| Not an inconsistency | A reviewer rejected it |
| Resolved | A reviewer explained the difference |

### Events

proposed (awaiting a reviewer) · confirmed (accounts are compared) · rejected (not one
occurrence)

### Entities

unresolved · confirmed · merged · rejected. Possible duplicates can also be marked
**deferred**.

### Transcript segments

Unreviewed · Corrected by a reviewer

### Cases

open · archived

### Other

- **AI processing**: allowed / off.
- **Audit chain**: intact / broken.

### The different "confidence" numbers

None of these is the probability that something is true.

| Number | What it means |
|---|---|
| Engine confidence | How sure OCR or speech recognition was about the text it read |
| Extraction confidence | The AI's self-assessment of a claim; "not applicable" for rule-based claims |
| Detection confidence | How cleanly a rule matched a potential inconsistency |
| Association score | How strongly the rules linked accounts into an event |
| Duplicate score | Ordering aid for possible duplicate entities |

---

## 28. A complete example, start to finish

*A fictional case: a pallet of goods may have gone missing between a supplier and a
warehouse.*

1. **Create the investigation.** On the dashboard, choose **New investigation**. Title:
   "Missing pallet shipment". You are now the owner.
2. **Upload evidence.** On the Evidence tab, drop in:
   - `delivery-receipt.pdf`
   - `gate-photo.jpg`
   - `witness-call.m4a`
   - `dashcam.mp4`
   - `supplier-email.eml`
   - `stock-ledger.xlsx`

   Keep each file under 4.5 MB. All six appear as **Pending**. The photo, recording and
   video show **Awaiting worker**.
3. **Process the files.** Choose **Process all pending**. The PDF, e-mail and spreadsheet
   are processed by the website and turn **Completed**. The worker processes the photo,
   recording and video. **Refresh** to see them turn Completed.
   *If something fails, read the reason under the file.*
4. **Review extracted text and transcripts.** *(manual review)* Open each file's
   workspace. Check that the receipt's text boxes match the page. Listen to the call and
   correct any misheard words with **Correct transcript**.
5. **Run the analysis.** Choose **Run analysis** (the worker may already have run it).
   Claims, entities and event proposals appear.
6. **Examine claims.** *(manual review)* On the Claims tab, open each important claim
   with **Show in source**, then **Verify**, mark **Needs verification**, or **Reject**.
7. **Examine entities.** *(manual review)* On the Entities tab, check that shipment
   NS-88421 links the receipt, the e-mail and the ledger. Decide each possible duplicate:
   merge, different, or decide later.
8. **Examine events.** *(manual review)* On the Events tab, open "Arrival of KX-4471". If
   the accounts really describe one arrival, choose **Same occurrence: confirm**.
9. **Review possible inconsistencies.** *(manual review)* On the Inconsistencies tab,
   open "Potential temporal inconsistency": the receipt says 10:30 and the witness says
   about 11:15. Read the alternative explanations (rounding, a clock set differently, two
   visits). Add your own if you know more. Then choose **Confirm inconsistency**, **Mark
   unresolved**, **Resolve** (with a note) or **Reject**.
10. **Check the results.** Use the Overview, Timeline, Graph and Review queue tabs to see
    what is left. Use **Search & ask** to look things up.
11. **Generate a report.** On the Reports tab, choose **Investigation report → Generate
    PDF**. Preview it and download it. Note its version and hash.
12. **Check the audit trail.** On the Audit tab, confirm **Audit chain intact**. Every
    decision you made is listed with your account name.

Steps 4 and 6 to 9 always need a person. EvidenceX never confirms, verifies or resolves
anything by itself.

---

## 29. Quick reference

### Glossary

| Term | Meaning |
|---|---|
| **Investigation / case** | A private workspace holding the files and findings for one matter |
| **Evidence** | A file uploaded to a case |
| **Processing / extraction** | Reading a file and turning it into text segments |
| **Segment** | A small piece of extracted text, such as a line, block, row or spoken passage |
| **Locator** | Where a segment came from: page and box, pixel area, time, row and column, or e-mail part |
| **Run** | One processing attempt for a file; earlier runs are kept |
| **OCR** | Reading written or printed text from an image or scan |
| **Transcription** | Turning spoken audio into written text |
| **Claim** | A checkable statement found in the evidence, with its exact quote |
| **Entity** | An identifiable thing mentioned in the evidence, such as an identifier, plate, place or e-mail contact |
| **Event** | A proposed group of claims that may describe one real-world occurrence |
| **Potential inconsistency / contradiction** | Two claims that appear to disagree, for human review |
| **Alternative explanation** | A harmless reason two sources may differ |
| **Reviewer decision** | A person's verify, reject, confirm or resolve choice, recorded in the audit trail |
| **SHA-256 / hash / fingerprint** | A code computed from a file's content; it identifies the file but does not prove it is genuine |
| **Audit chain** | The linked record of decisions; any later edit breaks the chain |
| **Processing worker** | The separate computer that does OCR, speech and video for the deployed website |
| **Awaiting worker** | A file waiting for that computer |
| **Rule-based** | Done by fixed rules, without AI |
| **AI consent** | The owner's switch allowing a case's extracted text to be sent to the AI provider |

### How to use EvidenceX: checklist

- [ ] Create an account and sign in.
- [ ] Create an investigation.
- [ ] Add members and choose their roles (owner).
- [ ] Upload evidence (4.5 MB maximum per file on the current deployment).
- [ ] Process the files, and make sure the worker is running for images, audio and video.
- [ ] Refresh the page to see the worker's results.
- [ ] Check extracted text and correct transcripts.
- [ ] Run the analysis.
- [ ] Verify or reject important claims.
- [ ] Decide on possible duplicate entities.
- [ ] Confirm or reject proposed events.
- [ ] Review each potential inconsistency and its alternative explanations.
- [ ] Clear the review queue.
- [ ] Generate and download a report.
- [ ] Check that the audit chain is intact.

### Common problems and what they mean

| What you see | What it means | What to do |
|---|---|---|
| **Awaiting worker** on images, audio or video | These are processed by the local worker | Make sure the worker is running, then refresh the page |
| A file stays **Awaiting worker** for a long time | The worker is not running, or cannot reach the database or storage | Ask the worker operator to check it |
| Failed: **Required component missing** | The engine was missing where processing ran | For worker file types, the worker retries by itself |
| Failed: **Interrupted before finishing** | Processing was stopped part-way | The worker retries it on its next run |
| Failed: **Internal error** on a worker file type | Often the storage service refused or could not be reached | The worker operator fixes the cause, then retries with `--retry-failed` |
| Failed: **Stored file missing** | The file is not in storage | Upload the file again |
| Upload refused as too large | Over the 4.5 MB hosting limit | Use a smaller file (compress or split it) |
| Upload refused: unsupported type | The file ending or content is not supported | Convert it to a supported format |
| **Requires OCR** on a PDF | It is a scan, and no OCR ran | The worker re-reads scanned PDFs once, when it can |
| "This case has not been analysed yet" | Nobody has run the analysis | An editor or owner chooses **Run analysis** |
| "The latest analysis found no claims" | The rules found no times, dates, amounts, identifiers or places | Check the extracted text; this does not mean the file contains none |
| "This action needs the 'editor' role…" | Your role does not allow this | Ask the case owner for a higher role |
| "This case could not be found…" | You are not a member, or it was deleted | Ask the owner to add you |
| Ask shows "Source passages only (no AI)" | No AI key is configured, or AI is not allowed for the case | This is expected; the passages and their sources are still shown |
| "The default speech model is not on disk" | True only for the website's server | Ignore it; the worker uses its own model |
| Video frame pictures do not appear | Frame previews need a library the website's server does not have | The text and transcript still appear after worker processing |
| **Audit chain broken** | A recorded decision was changed or removed outside EvidenceX | Report it to the system operator |

### Feature availability (current deployment)

| Feature | What it does | Availability | Requirements or limitations |
|---|---|---|---|
| Accounts, sign-in, sessions | Personal access to EvidenceX | Available | Sign-in lockout after repeated failures; no password reset |
| Demo investigation | A private, fictional example case for each user | Available | Photo, video and recording need the local worker |
| Cases: create, edit, archive, delete | Organise work into private investigations | Available | Delete is owner-only and permanent |
| Members and roles | Share a case with set permissions | Available | The person must already have an account |
| Evidence upload, download, delete | Add and retrieve files | Available | 4.5 MB per file on the current deployment |
| Upload validation and fingerprint | Check file content; compute SHA-256 | Available | The fingerprint does not prove authenticity |
| PDF text extraction and page preview | Read text-layer PDFs | Available | Up to 500 pages by default |
| Spreadsheet (CSV, XLSX) extraction | Read rows and cells | Available | Formulas are shown, never calculated |
| E-mail (EML) extraction | Read headers and body; list attachments | Available | Attachments are listed, never opened |
| Image OCR | Read text in photos and scans | Available with local worker | Needs the worker running with Tesseract |
| Scanned-PDF OCR | Read scanned PDF pages | Available with local worker | Re-run once by the worker when the website could not OCR the pages |
| Audio transcription | Turn speech into text with times | Available with local worker | Needs faster-whisper and a model on the worker; 20 minutes maximum by default |
| Video processing | Sampled frames, frame text, soundtrack | Available with local worker | Needs PyAV, Tesseract and a speech model on the worker; sampled frames only |
| Video frame preview pictures | Show a single frame as an image | Partially available | Not on the deployed website; works where PyAV is installed |
| Transcript correction | Save a corrected transcript next to the original | Available | The original text is never changed |
| Per-file speech model choice | Pick a speech model for one run | Partially available | Affects website processing only, which has no model; the worker uses its own |
| Per-file OCR language choice | Pick OCR languages for one run | Not implemented | Exists in the API only; no website control |
| Run analysis | Extract claims, entities, events and inconsistencies | Available | Rule-based unless AI is configured and allowed |
| Claims and claim review | Statements with quotes; verify, reject, edit | Available | Rules find explicit times, dates, amounts, identifiers and places only |
| Entities and duplicate review | Link files through shared identifiers | Available | No names of people or organisations from free text |
| Event proposals and review | Group accounts of one occurrence | Partially available | Confirm, reject, reopen, remove and note work; manual create, split and add-claim are API only |
| Relationship review | Accept or reject links between claims | Partially available | Relationships are shown; reviewing them is API only |
| Timeline | Chronological view of dated claims | Available | Undated claims are listed separately |
| Potential inconsistencies | Flag disagreeing claims for review | Available | Times, quantities and sequence only; no location conflicts |
| Alternative explanations | Harmless reasons for differences | Available | Machine hypotheses are suggestions, not findings |
| Knowledge graph and JSON/GraphML export | Network view of the case | Available | At most 250 nodes on screen |
| Search | Keyword search across the case | Available | Not AI-based; runs inside EvidenceX |
| Ask (source passages) | Answer questions with cited passages | Available | Passages are shown word for word |
| Ask (AI answers) | AI-written answers with citations | Requires configuration | AI key plus owner consent; not live-tested |
| AI claim extraction | Use AI to find claims | Requires configuration | AI key, AI mode plus owner consent; not live-tested |
| AI report summary | AI-drafted report summary | Not implemented | Backend support exists, but the website has no option to request it |
| Investigation and graph PDF reports | Versioned, hashed PDF reports | Available | Generating needs the reviewer role |
| Review queue | List of items awaiting decisions | Available | An empty queue is not a verification |
| Audit trail and chain check | Tamper-evident record of decisions | Available | Records from before chaining are not chained |
| Automatic page refresh for worker results | Show worker results without reloading | Partially available | Updates while a file is processing; otherwise refresh the page |
| Large uploads (direct to storage) | Upload files over 4.5 MB on the deployment | Not implemented | Planned enhancement only |
| Password reset | Recover a forgotten password | Not implemented | — |

---

*EvidenceX is an analytical aid. It does not determine guilt or innocence, does not
detect lies or deception, and does not authenticate evidence. Every finding is a lead for
a person to review.*
