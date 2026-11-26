// Pure helpers for audio transcripts. No React, no imports, no side effects, so they
// can be tested directly with Node's test runner (frontend/tests/).
//
// Nothing here changes transcript text. The stored segment text is the original
// machine transcription and is always shown exactly as stored.

export interface TranscriptWord {
  word: string;
  start: number; // seconds, as stored
  end: number;
  /** Engine-reported probability 0..1, or null when the engine gave none. */
  probability: number | null;
  /** True when the extractor listed this word in `low_probability_words`. */
  flagged: boolean;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * Words of an audio segment with the extractor's flags applied, or null when the
 * segment has no valid word data (for example a run made before word timestamps).
 *
 * `low_probability_words` lists flagged words in transcript order, so it is matched
 * against `words` in order. The same spelling elsewhere in the segment is only
 * flagged if the extractor listed it again.
 */
export function parseTranscriptWords(data: unknown): TranscriptWord[] | null {
  if (!isRecord(data) || !Array.isArray(data.words)) return null;
  const flaggedList = Array.isArray(data.low_probability_words)
    ? data.low_probability_words.filter((w): w is string => typeof w === "string")
    : [];
  const words: TranscriptWord[] = [];
  let next = 0;
  for (const raw of data.words) {
    if (!isRecord(raw) || typeof raw.word !== "string") return null;
    const start = finite(raw.start);
    const end = finite(raw.end);
    if (start === null || end === null) return null;
    const probability = finite(raw.probability);
    const flagged = next < flaggedList.length && flaggedList[next] === raw.word;
    if (flagged) next += 1;
    words.push({ word: raw.word, start, end, probability, flagged });
  }
  return words;
}

export interface TranscriptSpan {
  /** A slice of the stored transcript text, exactly as stored. */
  text: string;
  /** The word this slice corresponds to, when it is one of the engine's word tokens. */
  word: TranscriptWord | null;
}

/**
 * The stored transcript split into slices for display, so engine-flagged words can be
 * highlighted INSIDE the original text. Joining the slices always gives back `text`
 * exactly: nothing is re-spaced, re-punctuated or rebuilt from tokens.
 *
 * Each token is looked up in the text after the previous one. If a token cannot be
 * found (the token list and the text disagree), the rest of the text is returned as one
 * plain slice and no further words are marked; the text itself is never altered.
 */
export function transcriptSpans(
  text: string | null | undefined,
  words: TranscriptWord[] | null,
): TranscriptSpan[] {
  const source = text ?? "";
  if (!source) return [];
  if (!words || words.length === 0) return [{ text: source, word: null }];
  const spans: TranscriptSpan[] = [];
  let cursor = 0;
  for (const w of words) {
    const token = w.word;
    if (!token) continue;
    const at = source.indexOf(token, cursor);
    if (at < 0) break;
    if (at > cursor) spans.push({ text: source.slice(cursor, at), word: null });
    spans.push({ text: source.slice(at, at + token.length), word: w });
    cursor = at + token.length;
  }
  if (cursor < source.length) spans.push({ text: source.slice(cursor), word: null });
  return spans;
}

/** "19%" for 0.189. Values outside 0..1 are shown as they are, never adjusted. */
export function formatProbability(probability: number | null): string {
  if (probability === null) return "not reported";
  return `${Math.round(probability * 100)}%`;
}

/** True for a segment produced by speech transcription. */
export function isAudioTranscript(segment: {
  segment_type: string;
  locator: { kind: string } | null | undefined;
}): boolean {
  return segment.segment_type === "transcript_segment" || segment.locator?.kind === "audio";
}

// --- playback -----------------------------------------------------------------------

export interface PlaybackWindow {
  start: number;
  end: number;
}

/**
 * A safe playback window for a segment. Returns null when the times are unusable.
 * When the media duration is known, the window is kept inside it.
 */
export function playbackWindow(
  start: number,
  end: number,
  mediaDuration?: number | null,
): PlaybackWindow | null {
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end < start) return null;
  if (mediaDuration !== undefined && mediaDuration !== null && Number.isFinite(mediaDuration)) {
    if (start >= mediaDuration) return null;
    return { start, end: Math.min(end, mediaDuration) };
  }
  return { start, end };
}

/** True once playback has reached the end of the window and should stop. */
export function shouldStopPlayback(currentTime: number, window: PlaybackWindow): boolean {
  return currentTime >= window.end;
}

export type PlaybackState = "idle" | "loading" | "playing" | "error" | "unsupported";

/** User-facing text for a playback problem. Never includes paths or server detail. */
export function playbackErrorText(kind: "missing" | "decode" | "unsupported" | "other"): string {
  switch (kind) {
    case "missing":
      return "The original recording could not be loaded. It may have been removed.";
    case "decode":
      return "This browser cannot play this recording. Download it to listen.";
    case "unsupported":
      return "Audio playback is not supported in this browser.";
    default:
      return "Playback failed. Try again or download the recording.";
  }
}

export const VERIFY_NOTICE =
  "AI-generated transcription. Names, identifiers, dates, numbers and times may be " +
  "misheard and must be checked against the original recording.";
