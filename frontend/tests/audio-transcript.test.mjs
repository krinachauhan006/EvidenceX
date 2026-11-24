// Tests for the pure audio transcript helpers.
// Run: node --experimental-strip-types --test tests/
// No test framework is installed; this uses Node's built-in runner only.

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  VERIFY_NOTICE,
  formatProbability,
  isAudioTranscript,
  parseTranscriptWords,
  playbackErrorText,
  playbackWindow,
  shouldStopPlayback,
} from "../components/evidence/audio-transcript.ts";

const words = [
  { word: "I", start: 0, end: 0.12, probability: 0.79 },
  { word: "am", start: 0.12, end: 0.26, probability: 0.78 },
  { word: "not", start: 0.26, end: 0.46, probability: 0.95 },
  { word: "served", start: 0.46, end: 0.8, probability: 0.189 },
  { word: "in", start: 0.8, end: 1.12, probability: 0.565 },
  { word: "the", start: 1.12, end: 1.22, probability: 0.543 },
  { word: "next", start: 1.22, end: 1.5, probability: 0.208 },
  { word: "time.", start: 1.5, end: 2.24, probability: 0.948 },
];

test("flagged words are exactly those listed in low_probability_words", () => {
  const parsed = parseTranscriptWords({ words, low_probability_words: ["served", "next"] });
  assert.deepEqual(
    parsed.filter((w) => w.flagged).map((w) => w.word),
    ["served", "next"],
  );
  assert.equal(parsed.length, 8);
});

test("words keep their stored timestamps and engine probabilities unchanged", () => {
  const parsed = parseTranscriptWords({ words, low_probability_words: ["served"] });
  const served = parsed.find((w) => w.word === "served");
  assert.deepEqual(served, {
    word: "served",
    start: 0.46,
    end: 0.8,
    probability: 0.189,
    flagged: true,
  });
});

test("flag matching follows transcript order, not spelling alone", () => {
  const repeated = [
    { word: "the", start: 0, end: 0.1, probability: 0.9 },
    { word: "the", start: 0.1, end: 0.2, probability: 0.2 },
  ];
  const parsed = parseTranscriptWords({ words: repeated, low_probability_words: ["the"] });
  assert.deepEqual(parsed.map((w) => w.flagged), [true, false]);
});

test("no flags when the list is missing or empty", () => {
  assert.ok(parseTranscriptWords({ words }).every((w) => !w.flagged));
  assert.ok(parseTranscriptWords({ words, low_probability_words: [] }).every((w) => !w.flagged));
});

test("segments without word data return null (older runs)", () => {
  assert.equal(parseTranscriptWords(null), null);
  assert.equal(parseTranscriptWords({ source: "machine_transcription" }), null);
  assert.equal(parseTranscriptWords({ words: "nope" }), null);
});

test("malformed word entries are rejected rather than guessed", () => {
  assert.equal(parseTranscriptWords({ words: [{ word: "x", start: "0", end: 1 }] }), null);
  assert.equal(parseTranscriptWords({ words: [{ start: 0, end: 1 }] }), null);
});

test("a missing probability stays missing", () => {
  const parsed = parseTranscriptWords({ words: [{ word: "x", start: 0, end: 1 }] });
  assert.equal(parsed[0].probability, null);
  assert.equal(formatProbability(null), "not reported");
});

test("probabilities are shown as rounded percentages", () => {
  assert.equal(formatProbability(0.189), "19%");
  assert.equal(formatProbability(0.502), "50%");
  assert.equal(formatProbability(1), "100%");
});

test("audio transcripts are recognised by type or locator", () => {
  assert.ok(isAudioTranscript({ segment_type: "transcript_segment", locator: { kind: "audio" } }));
  assert.ok(isAudioTranscript({ segment_type: "other", locator: { kind: "audio" } }));
  assert.ok(!isAudioTranscript({ segment_type: "table_row", locator: { kind: "csv" } }));
  assert.ok(!isAudioTranscript({ segment_type: "ocr_line", locator: null }));
});

test("playback window starts at the segment start and ends at its end", () => {
  assert.deepEqual(playbackWindow(2.8, 7.4), { start: 2.8, end: 7.4 });
  assert.deepEqual(playbackWindow(2.8, 9.0, 7.58), { start: 2.8, end: 7.58 });
});

test("unusable playback windows are refused", () => {
  assert.equal(playbackWindow(-1, 2), null);
  assert.equal(playbackWindow(3, 2), null);
  assert.equal(playbackWindow(Number.NaN, 2), null);
  assert.equal(playbackWindow(8, 9, 7.5), null); // starts after the recording ends
});

test("playback stops once the segment end is reached", () => {
  const window = { start: 1, end: 2.5 };
  assert.equal(shouldStopPlayback(2.4, window), false);
  assert.equal(shouldStopPlayback(2.5, window), true);
  assert.equal(shouldStopPlayback(3.0, window), true);
});

test("playback error messages are plain and reveal no paths", () => {
  for (const kind of ["missing", "decode", "unsupported", "other"]) {
    const text = playbackErrorText(kind);
    assert.ok(text.length > 10);
    assert.ok(!/[\\/]var[\\/]|storage|http/i.test(text));
  }
});

test("the verification notice names the risky kinds of content", () => {
  for (const word of ["AI-generated", "Names", "identifiers", "dates", "numbers", "times"]) {
    assert.ok(VERIFY_NOTICE.includes(word), word);
  }
});
