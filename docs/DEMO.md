# Demo guide (under 3 minutes)

Uses the fictional files in `sample-evidence/demo-missing-shipment/`. Run through the
whole flow once before recording: narrate only what your own run shows.

## Before recording
- Backend and frontend running (`README.md`). Tesseract installed for OCR; the speech
  model is optional (the demo audio has no speech).
- Use a fresh browser profile and a demo account, for example `demo@example.org`. Do not
  record a real account or real evidence.

## Script

| Time | On screen | Say |
|---|---|---|
| 0:00 | Landing page; the hero animation plays | "EvidenceX: one case, multiple evidence formats, connected findings. Six fictional files become cited claims and one suggested event, and it ends with a possible inconsistency waiting for a person." |
| 0:15 | Hover a source in the hero, then **Start an Investigation** | "Every claim traces back to its exact source." |
| 0:20 | Register, land in the workspace | "Accounts and sessions are server-side; each case is private to its members." |
| 0:30 | **New investigation** → title "Missing pallet shipment (demo)" | |
| 0:35 | Upload all six files at once | "PDF, photo, audio, video, e-mail and a spreadsheet. The real type is checked from the file's content, and each file is processed on its own." |
| 0:55 | Evidence list turns green; open the PDF, click a claim | "Here is the claim, and here is the exact box on the page it came from." |
| 1:10 | Open the gate photo, then the video frame | "OCR regions on the image; the video is read through sampled frames with their timestamps." |
| 1:25 | **Run analysis** → **Events** | "EvidenceX proposes that these accounts describe one arrival and explains why. The link is weak, so it waits for a reviewer." |
| 1:40 | **Confirm** the arrival event | "Only after a person confirms the grouping are the accounts compared." |
| 1:50 | **Contradictions** → open one | "A possible inconsistency: 10:30 on the receipt versus the witness's time. Its alternative explanations: rounding, two visits, a clock set differently. The confidence is a heuristic, not a probability. EvidenceX does not decide which account is right." |
| 2:15 | **Graph** → click the event node; export **JSON** or **GraphML** | "Evidence, entities, the event and the inconsistency, drawn only from stored records." |
| 2:30 | **Reports** → generate the **knowledge graph** and **investigation** reports, open the PDFs | "A narrative report: summary, evidence inventory, key claims with sources, events, inconsistencies with alternatives, gaps, and a qualified conclusion with references." |
| 2:45 | **Audit** | "Every decision is signed by the account that made it and hash-chained. People decide." |

## Honest notes for the voice-over
- The demo audio is a tone, so it yields no transcript. Say so if you show it.
- The analysis is rule-based unless you configure a Gemini key and enable AI for the
  case. Do not describe it as AI analysis otherwise.
- Never say EvidenceX detects lies, proves anything or decides guilt.

---
EvidenceX · Copyright (C) 2026 Krina R. Chauhan · GNU AGPL-3.0 ([LICENSE](../LICENSE))
