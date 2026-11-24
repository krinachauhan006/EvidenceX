# EvidenceX — Product

## What it is
EvidenceX is a Multimodal Evidence Intelligence and Investigation Platform. It
ingests heterogeneous evidence (PDFs, images, audio), extracts structured claims
with full source provenance, normalizes entities and events, detects cross-modal
contradictions, and presents everything in a single investigation workspace with
human review and report generation.

Built for the Kiroween 2026 hackathon, Frankenstein category. Sole developer.
Priority: a reliable, polished, demonstrable product by the deadline.

## Who it serves
Investigators, analysts, journalists, and researchers who must reason over large,
mixed-format evidence sets and need every conclusion traceable to its source.

## Core value proposition
1. **Unified intake** across PDF, image, and audio.
2. **Provenance-first extraction** — every claim links back to the exact source span.
3. **Cross-modal reasoning** — contradictions surfaced across documents and modalities.
4. **Human-in-the-loop** — the system assists; people decide.

## Product principles
1. Build a working product incrementally; each increment is demonstrable.
2. Prioritise source provenance and reliability above feature count.
3. Every extracted claim must reference its original evidence span.
4. Every finding must reference valid, existing claims and sources.
5. Distinguish extraction confidence from factual truth — never conflate them.
6. Preserve uncertainty in dates, times, and statements; never fabricate precision.
7. Never claim to determine guilt, detect lies, or authenticate evidence. EvidenceX
   surfaces and organizes; it does not adjudicate.
8. Treat all uploaded files as untrusted input.
9. Keep all AI outputs validated through structured schemas.
10. Avoid unnecessary microservices or excessive agent frameworks.

## What EvidenceX explicitly does NOT do
- It does not render verdicts of guilt or innocence.
- It does not claim to detect deception or lies.
- It does not authenticate or certify evidence as genuine.
- It does not present extraction confidence as factual certainty.

## MVP scope (hackathon)
Case management, evidence upload + validation, PDF/image/audio processing with
segment-level provenance, schema-validated claim extraction, basic entity/event
normalization, temporal contradiction detection, investigation workspace with
claim-to-source highlighting, human review (accept/reject/edit), and simple
report generation.

## Deferred
Full non-temporal contradiction types, React Flow relationship graph, video
support, advanced coreference/entity resolution, task queue, multi-user auth.
