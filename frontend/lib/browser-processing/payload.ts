// Request bodies for the browser-processing endpoints, mirroring
// backend/app/modules/processing/browser_schemas.py. Pure (unit-tested).

// Type-only imports (erased at runtime), so Node's test runner can load this file.
import type { OcrLine } from "./ocr-lines";
import type { TranscriptSegment } from "./transcript";

export type BrowserFailureCode =
  | "interrupted"
  | "browser_engine_failed"
  | "browser_decode_failed"
  | "browser_out_of_memory";

export interface BrowserEngineInfo {
  ocr_engine_version?: string | null;
  speech_engine_version?: string | null;
  speech_model?: string | null;
  device?: "wasm" | "webgpu" | null;
}

export interface ImageResult {
  kind: "image";
  width: number;
  height: number;
  language: string;
  lines: OcrLine[];
}

export interface AudioResult {
  kind: "audio";
  duration_seconds: number;
  language: string | null;
  segments: TranscriptSegment[];
}

export interface VideoFrame {
  t: number;
  sampling: "first_frame" | "interval";
  lines: OcrLine[];
}

export interface VideoResult {
  kind: "video";
  duration_seconds: number;
  frame_width: number;
  frame_height: number;
  interval_seconds: number;
  ocr_language: string;
  frames: VideoFrame[];
  soundtrack: "transcribed" | "no_audio_track" | "not_transcribed";
  transcript_language: string | null;
  transcript: TranscriptSegment[];
}

export type BrowserResult = ImageResult | AudioResult | VideoResult;

export interface BrowserResultBody {
  run_number: number;
  source_sha256: string;
  duration_ms: number;
  engine: BrowserEngineInfo;
  result: BrowserResult;
}

export interface BrowserClaim {
  evidence_id: string;
  run_number: number;
  kind: "image" | "audio" | "video";
  mime_type: string;
  sha256: string;
  byte_size: number;
  heartbeat_seconds: number;
  stale_seconds: number;
  ocr_language: string;
  limits: {
    max_extracted_chars: number;
    max_audio_seconds: number;
    max_video_seconds: number;
    video_max_frames: number;
    video_frame_interval_seconds: number;
  };
}

// The hosting platform limits a request body (Vercel: 4.5 MB). Stay safely below it.
export const MAX_BODY_BYTES = 4_000_000;

function withoutWords(result: BrowserResult): BrowserResult {
  const strip = (lines: OcrLine[]) => lines.map((l) => ({ ...l, words: [] }));
  if (result.kind === "image") return { ...result, lines: strip(result.lines) };
  if (result.kind === "video") {
    return { ...result, frames: result.frames.map((f) => ({ ...f, lines: strip(f.lines) })) };
  }
  return result;
}

/**
 * The JSON body to submit. When it is too large for the platform, per-word boxes are
 * dropped first (line text, line boxes and line confidence are kept). Returns null when
 * even that is too large; the caller then reports the item as not processable here.
 */
export function encodeResultBody(body: BrowserResultBody, maxBytes = MAX_BODY_BYTES): string | null {
  const size = (s: string) => new TextEncoder().encode(s).length;
  const full = JSON.stringify(body);
  if (size(full) <= maxBytes) return full;
  const slim = JSON.stringify({ ...body, result: withoutWords(body.result) });
  return size(slim) <= maxBytes ? slim : null;
}

/** Lower-case hex SHA-256 of the bytes (Web Crypto). */
export async function sha256Hex(data: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}
