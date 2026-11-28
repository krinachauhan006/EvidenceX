// Whisper (Transformers.js) chunks -> transcript segments, and the video frame
// schedule. Pure (unit-tested).

export interface WhisperChunk {
  text: string;
  /** [start, end] in seconds; Whisper leaves `end` null for a final cut-off chunk. */
  timestamp: [number | null, number | null];
}

export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
}

const round3 = (v: number) => Math.round(v * 1000) / 1000;

/**
 * Segments with times inside [0, duration]: a missing start follows the previous
 * segment, a missing end becomes the end of the recording, and empty text is dropped.
 * Text is trimmed and otherwise kept exactly as the engine produced it.
 */
export function segmentsFromChunks(
  chunks: readonly WhisperChunk[] | null | undefined,
  duration: number,
): TranscriptSegment[] {
  const out: TranscriptSegment[] = [];
  let previousEnd = 0;
  for (const chunk of chunks ?? []) {
    const text = (chunk.text ?? "").trim().slice(0, 20_000);
    const [rawStart, rawEnd] = chunk.timestamp ?? [null, null];
    const start = Number.isFinite(rawStart) ? Math.min(Math.max(rawStart as number, 0), duration) : previousEnd;
    let end = Number.isFinite(rawEnd) ? Math.min(Math.max(rawEnd as number, 0), duration) : duration;
    if (end < start) end = start;
    previousEnd = end;
    if (!text) continue;
    out.push({ start: round3(start), end: round3(end), text });
  }
  return out;
}

export interface FrameSchedule {
  /** Seconds, ascending, unique. The first is always 0 ("first_frame"). */
  times: number[];
  interval: number;
}

/**
 * Bounded frame sampling: one frame every `interval` seconds (at least the server's
 * VIDEO_FRAME_INTERVAL_SECONDS, widened for long videos) and never more than
 * `maxFrames` + 1 frames in total, so memory and time stay bounded.
 */
export function frameSchedule(duration: number, interval: number, maxFrames: number): FrameSchedule {
  if (!(duration > 0)) return { times: [0], interval };
  const step = Math.max(interval, duration / Math.max(1, maxFrames));
  const times = [0];
  for (let t = step; t < duration && times.length < maxFrames + 1; t += step) {
    times.push(round3(t));
  }
  return { times, interval: round3(step) };
}
