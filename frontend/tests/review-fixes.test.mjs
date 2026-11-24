// Regression tests for the Phase 1 browser-review defects D1-D11.
// Run: node --experimental-strip-types --no-warnings --test tests/review-fixes.test.mjs
//
// Behaviour tests cover the pure helpers. D5, D6, D9, D10 and D11 are CSS/copy/asset
// fixes; they get source-contract checks here (reading the component files) so the
// specific defects cannot silently return, and are also verified in a browser.

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  analysisPhase,
  countHint,
  countTone,
  countValue,
  emptyStateCopy,
  phaseNotice,
} from "../components/analysis/analysis-state.ts";
import { parseTranscriptWords, transcriptSpans } from "../components/evidence/audio-transcript.ts";
import { rowDetail } from "../components/workspace/table-detail.ts";
import { canRetry, errorKind } from "../components/ui/error-kind.ts";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = (p) => readFileSync(join(ROOT, p), "utf8");

// --- D4: verbatim transcript ---------------------------------------------------------

function words(tokens, flagged = []) {
  return parseTranscriptWords({
    words: tokens.map((w, i) => ({ word: w, start: i, end: i + 0.5, probability: 0.9 })),
    low_probability_words: flagged,
  });
}
const joined = (spans) => spans.map((s) => s.text).join("");

const CASES = [
  // [stored text, tokens as the engine stores them (stripped), what naive joining gives]
  ["I know this at about 7.15, source unknown.",
    ["I", "know", "this", "at", "about", "7", ".15,", "source", "unknown."]],
  // Contractions split into separate tokens, as speech engines can produce them.
  ["It's done, isn't it?", ["It", "'s", "done,", "isn", "'t", "it?"]],
  ["We can't say; they'll check.", ["We", "can", "'t", "say;", "they", "'ll", "check."]],
  ["Shipment NS-88421 arrived at 10:30.", ["Shipment", "NS", "-88421", "arrived", "at", "10", ":30."]],
  ["Total: $1,250.00 (approx.)", ["Total:", "$1", ",250", ".00", "(approx.)"]],
  ["Hello—world", ["Hello", "—world"]],
  ["  leading and trailing spaces  ", ["leading", "and", "trailing", "spaces"]],
];

test("D4: displayed transcript is byte-identical to the stored text", () => {
  for (const [text, tokens] of CASES) {
    const spans = transcriptSpans(text, words(tokens));
    assert.equal(joined(spans), text, text);
  }
});

test("D4: the cases above are ones where naive token joining would change the text", () => {
  for (const [text, tokens] of CASES) {
    assert.notEqual(tokens.join(" "), text, `test case must be meaningful: ${text}`);
  }
});

test("D4: decimal kept intact ('7.15', not '7 .15')", () => {
  const spans = transcriptSpans("at about 7.15, source", words(["at", "about", "7", ".15,", "source"]));
  assert.ok(joined(spans).includes("7.15,"));
  assert.ok(!joined(spans).includes("7 .15"));
});

test("D4: flagged words are highlighted inside the original text, in order", () => {
  const text = "I know this to know direct the footage at about 7.15, source unknown.";
  const tokens = ["I", "know", "this", "to", "know", "direct", "the", "footage", "at", "about", "7", ".15,", "source", "unknown."];
  const spans = transcriptSpans(text, words(tokens, ["to", "know", "direct", "footage", "7"]));
  assert.equal(joined(spans), text);
  const flagged = spans.filter((s) => s.word?.flagged).map((s) => s.text);
  assert.deepEqual(flagged, ["to", "know", "direct", "footage", "7"]);
  // The first "know" is NOT flagged; the second one is (order-based matching).
  const knows = spans.filter((s) => s.text === "know");
  assert.deepEqual(knows.map((s) => s.word.flagged), [false, true]);
});

test("D4: tokens that disagree with the text never alter it", () => {
  const text = "The engine heard something else.";
  const spans = transcriptSpans(text, words(["The", "engine", "herd", "something"], ["something"]));
  assert.equal(joined(spans), text);
  // Matching stops at the first token not found; the rest is one plain slice.
  assert.equal(spans.filter((s) => s.word).length, 2);
});

test("D4: no words, empty or missing text", () => {
  assert.deepEqual(transcriptSpans("Plain text.", null), [{ text: "Plain text.", word: null }]);
  assert.deepEqual(transcriptSpans("", words(["x"])), []);
  assert.deepEqual(transcriptSpans(null, null), []);
});

test("D4: audio workspace renders the stored text, not tokens joined with spaces", () => {
  const viewer = src("components/workspace/audio-viewer.tsx");
  assert.match(viewer, /transcriptSpans\(s\.text, words\)/);
  assert.match(viewer, /exactly as stored/);
  assert.match(viewer, /AI-generated transcription/);
  assert.match(viewer, /Unreviewed/);
  // The old flex/gap rendering that inserted visual spaces between tokens is gone
  // from the transcript paragraph.
  assert.doesNotMatch(viewer, /flex flex-wrap gap-x-1 gap-y-0\.5/);
});

// --- D1, D2, D3: analysis phases and empty states -----------------------------------

test("phase: unknown until loaded, never/running/completed/failed from the run", () => {
  assert.equal(analysisPhase(null, false), "unknown");
  assert.equal(analysisPhase(null, true), "never");
  assert.equal(analysisPhase({ status: "running" }, true), "running");
  assert.equal(analysisPhase({ status: "completed" }, true), "completed");
  assert.equal(analysisPhase({ status: "failed" }, true), "failed");
  assert.equal(analysisPhase({ status: "weird" }, true), "unknown");
});

const ALL_KINDS = ["claims", "contradictions", "review", "entities", "graph"];
const ALL_PHASES = ["unknown", "never", "running", "completed", "failed"];
const text = (c) => `${c.title} ${c.body}`.toLowerCase();

test("D1/D2: before any analysis, nothing claims results or an all-clear", () => {
  for (const kind of ALL_KINDS) {
    const c = emptyStateCopy(kind, "never");
    assert.match(c.title, /not been analysed/);
    const t = text(c);
    assert.ok(!/detected|found no|nothing is waiting|nothing awaiting|left nothing/.test(t), `${kind}: ${t}`);
    assert.ok(/no analysis has been run/.test(t));
  }
});

test("D1: completed with zero findings says so, and disclaims what it does not mean", () => {
  const c = emptyStateCopy("contradictions", "completed");
  assert.match(c.title, /latest analysis found no potential inconsistencies/i);
  assert.match(c.body, /does not mean the sources agree/);
  assert.match(c.body, /location conflicts are not checked/);
});

test("D2: completed review queue with zero items does not imply verification", () => {
  const c = emptyStateCopy("review", "completed");
  assert.match(c.title, /latest analysis left nothing awaiting review/i);
  assert.match(c.body, /does not mean the evidence has been verified/);
});

test("Entities/Graph: zero after a completed analysis is described, not implied away", () => {
  const e = emptyStateCopy("entities", "completed");
  assert.match(e.title, /latest analysis found no entities/i);
  assert.match(e.body, /does not mean the evidence mentions none/);
  const g = emptyStateCopy("graph", "completed");
  assert.match(g.title, /latest analysis produced nothing to connect/i);
  assert.match(g.body, /does not mean the evidence items are unrelated/);
  assert.match(emptyStateCopy("graph", "completed", { filtered: true }).title, /match the filters/);
});

test("Entities/Graph pages use the phase-aware empty state", () => {
  const entities = src("app/(dashboard)/cases/[caseId]/entities/page.tsx");
  const graph = src("app/(dashboard)/cases/[caseId]/graph/page.tsx");
  assert.match(entities, /AnalysisEmptyState kind="entities"/);
  assert.doesNotMatch(entities, /Run the analysis to extract entities/);
  assert.match(graph, /AnalysisEmptyState kind="graph"/);
  assert.doesNotMatch(graph, /Nothing to show yet/);
});

test("running, failed and unknown are each distinct and say so", () => {
  for (const kind of ALL_KINDS) {
    assert.match(emptyStateCopy(kind, "running").title, /in progress/);
    assert.match(emptyStateCopy(kind, "failed").title, /failed/);
    assert.match(emptyStateCopy(kind, "unknown").title, /unavailable/);
  }
  const titles = new Set(ALL_PHASES.map((p) => emptyStateCopy("claims", p).title));
  assert.equal(titles.size, ALL_PHASES.length);
});

test("filters only change the copy after a completed analysis", () => {
  assert.match(emptyStateCopy("claims", "completed", { filtered: true }).title, /match the filters/);
  assert.match(emptyStateCopy("claims", "never", { filtered: true }).title, /not been analysed/);
});

test("no empty-state copy uses verdict language", () => {
  for (const kind of ALL_KINDS) {
    for (const phase of ALL_PHASES) {
      for (const filtered of [false, true]) {
        const t = text(emptyStateCopy(kind, phase, { filtered }));
        assert.ok(!/\b(lie|lying|guilt|guilty|fraud|proof|proves|authentic|true|truth)\b/.test(t), t);
      }
    }
  }
});

test("D2/D3: counts are never green; no number is shown before analysis", () => {
  for (const phase of ALL_PHASES) {
    for (const n of [0, 3]) assert.notEqual(countTone(n, phase), "green");
  }
  assert.equal(countValue(0, "never"), "—");
  assert.equal(countValue(0, "unknown"), "—");
  assert.equal(countValue(0, "completed"), "0");
  assert.equal(countTone(0, "completed"), "neutral");
  assert.equal(countTone(4, "completed"), "amber");
  assert.equal(countTone(0, "failed"), "red");
  assert.equal(countHint(0, "never"), "not analysed yet");
  assert.equal(countHint(0, "completed"), "none after the latest analysis");
  assert.equal(phaseNotice("completed"), null);
  assert.match(phaseNotice("failed"), /failed/);
});

test("D1/D2/D3: the pages use the phase-aware copy instead of the old wording", () => {
  const contradictions = src("app/(dashboard)/cases/[caseId]/contradictions/page.tsx");
  const review = src("app/(dashboard)/cases/[caseId]/review/page.tsx");
  const overview = src("app/(dashboard)/cases/[caseId]/page.tsx");
  const claims = src("app/(dashboard)/cases/[caseId]/claims/page.tsx");
  assert.doesNotMatch(contradictions, /None were detected with the current rules/);
  assert.match(contradictions, /AnalysisEmptyState kind="contradictions"/);
  assert.doesNotMatch(review, /Nothing is waiting for review/);
  assert.match(review, /AnalysisEmptyState kind="review"/);
  assert.doesNotMatch(review, /"amber" : "green"/);
  assert.doesNotMatch(overview, /review_queue \? "amber" : "green"/);
  assert.match(overview, /countTone\(data\.review_queue, analysisPhase\)/);
  assert.doesNotMatch(claims, /No claims match/);
  assert.match(claims, /AnalysisEmptyState/);
});

// --- D7: complete row detail ---------------------------------------------------------

test("D7: row detail keeps every value complete and in column order", () => {
  const long = "A very long description ".repeat(20) + "\nwith a second line";
  const cells = [
    { column: "b", value: long, coord: "B2", formula: null, noCachedValue: false, truncated: false },
    { column: "a", value: "  padded  ", coord: "A2", formula: null, noCachedValue: false, truncated: false },
    { column: "total", value: "", coord: "D2", formula: "=SUM(B2:C2)", noCachedValue: true, truncated: false },
    { column: "extra_1", value: "unexpected", coord: null, formula: null, noCachedValue: false, truncated: true },
  ];
  const d = rowDetail(cells, ["a", "b", "c", "total"], ["Alpha", "Beta", "", "Total"]);
  assert.deepEqual(d.map((e) => e.key), ["a", "b", "c", "total", "extra_1"]);
  assert.deepEqual(d.map((e) => e.label), ["Alpha", "Beta", "c", "Total", "extra_1"]);
  assert.equal(d[1].value, long); // never shortened
  assert.equal(d[0].value, "  padded  "); // never trimmed
  assert.equal(d[2].present, false);
  assert.equal(d[3].noCachedValue, true);
  assert.equal(d[3].formula, "=SUM(B2:C2)");
  assert.equal(d[4].truncatedAtExtraction, true);
});

test("D7: grid rows are top-aligned, nowrap with ellipsis, row number reachable", () => {
  const viewer = src("components/workspace/table-viewer.tsx");
  assert.match(viewer, /sticky left-0 z-10 border-r border-navy-800 px-1 py-0\.5 align-top/);
  assert.match(viewer, /max-w-\[16rem\] whitespace-nowrap px-2 py-1 align-top/);
  assert.match(viewer, /min-w-0 truncate/);
  assert.match(viewer, /show every cell in full/);
  assert.match(viewer, /RowDetailPanel/);
});

// --- D8: not-found handling ----------------------------------------------------------

test("D8: 404 is not retryable; network and server errors are", () => {
  assert.equal(errorKind(404), "not_found");
  assert.equal(canRetry(404), false);
  for (const s of [0, null, undefined, 500, 502, 503, 408, 429]) assert.equal(canRetry(s), true, String(s));
  for (const s of [400, 401, 403, 409, 422]) assert.equal(errorKind(s), "client");
});

test("D8: the workspace shows a not-found state with links, not the raw detail", () => {
  const ws = src("components/workspace/evidence-workspace.tsx");
  assert.match(ws, /errorKind\(evidence\.errorStatus\) === "not_found"/);
  assert.match(ws, /Evidence item not found/);
  assert.match(ws, /Back to the evidence library/);
  assert.doesNotMatch(ws, /message=\{evidence\.error\} onRetry=\{evidence\.reload\}/);
});

// --- D5, D6, D9, D10, D11: layout, copy, asset, colour -------------------------------

test("D5: case actions sit in a right-aligned column on large screens", () => {
  const shell = src("components/cases/case-shell.tsx");
  assert.match(shell, /lg:grid-cols-\[minmax\(0,1fr\)_auto\]/);
  assert.match(shell, /items-start gap-2 lg:items-end/);
  assert.match(shell, /justify-start gap-1\.5 lg:justify-end/);
});

test("D6: tab bars cannot overflow vertically and tabs no longer overhang", () => {
  const prim = src("components/ui/primitives.tsx");
  const shell = src("components/cases/case-shell.tsx");
  assert.match(prim, /TAB_BAR =\s*"flex gap-1 overflow-x-auto overflow-y-hidden/);
  assert.doesNotMatch(prim, /-mb-px/);
  assert.doesNotMatch(shell, /-mb-px/);
  assert.match(shell, /TAB_BAR/);
});

test("D9: evidence subtitle names every supported format", () => {
  const section = src("components/evidence/evidence-section.tsx");
  for (const f of ["PDF", "PNG", "JPG", "WebP", "WAV", "MP3", "M4A", "CSV", "XLSX", "EML"]) {
    assert.match(section, new RegExp(`\\b${f}\\b`), f);
  }
  assert.doesNotMatch(section, /Documents, images, audio, and CSV files/);
});

test("D10: an icon exists in the app directory (served by Next.js)", () => {
  assert.ok(existsSync(join(ROOT, "app", "icon.svg")));
  assert.ok(existsSync(join(ROOT, "app", "favicon.ico")));
  const ico = readFileSync(join(ROOT, "app", "favicon.ico"));
  assert.deepEqual([...ico.subarray(0, 4)], [0, 0, 1, 0]); // ICO header
});

test("D11: evidence-row delete uses destructive red, not the amber inconsistency colour", () => {
  const row = src("components/evidence/evidence-row.tsx");
  assert.doesNotMatch(row, /inconsistency/);
  assert.match(row, /border-failed\/40 px-2\.5 py-1\.5 text-xs text-failed hover:bg-failed\/10/);
  assert.match(row, /bg-failed px-3 py-1\.5/);
});
