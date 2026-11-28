// Main-thread side of in-browser speech recognition: decodes the recording to 16 kHz
// mono samples (Web Audio) and runs Whisper in a dedicated module worker
// (speech-worker.mjs, served from /engines; created only when needed and terminated
// afterwards to free memory).

import { EngineError, MediaDecodeError } from "./errors";
import { segmentsFromChunks, type TranscriptSegment, type WhisperChunk } from "./transcript";

export const SPEECH_MODEL = "onnx-community/whisper-tiny";
export const SPEECH_ENGINE_VERSION = "4.3.2"; // @huggingface/transformers, keep in step
export const SAMPLE_RATE = 16_000;
// In-browser transcription is English only for now: Transformers.js does not detect
// the language, and assuming it silently would misreport the run. Recorded on the run.
export const SPEECH_LANGUAGE = "english";

export type SpeechProgress = (
  stage: "loading" | "transcribing",
  fraction: number | null,
) => void;

/** Decode any browser-supported audio (or a video's soundtrack) to 16 kHz mono. */
export async function decodeToMono16k(data: ArrayBuffer): Promise<{ samples: Float32Array; duration: number }> {
  const w = window as unknown as {
    AudioContext?: typeof AudioContext;
    webkitAudioContext?: typeof AudioContext;
    OfflineAudioContext?: typeof OfflineAudioContext;
  };
  const Ctx = w.AudioContext ?? w.webkitAudioContext;
  if (!Ctx) throw new MediaDecodeError("Web Audio is not available.");
  let ctx: AudioContext;
  try {
    ctx = new Ctx({ sampleRate: SAMPLE_RATE });
  } catch {
    ctx = new Ctx();
  }
  let decoded: AudioBuffer;
  try {
    // decodeAudioData detaches the buffer it is given: pass a copy.
    decoded = await ctx.decodeAudioData(data.slice(0));
  } catch {
    throw new MediaDecodeError("The audio could not be decoded by this browser.");
  } finally {
    void ctx.close().catch(() => undefined);
  }
  let buffer = decoded;
  if (decoded.sampleRate !== SAMPLE_RATE && w.OfflineAudioContext) {
    const frames = Math.ceil(decoded.duration * SAMPLE_RATE);
    const offline = new w.OfflineAudioContext(1, Math.max(1, frames), SAMPLE_RATE);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    buffer = await offline.startRendering();
  }
  const samples = new Float32Array(buffer.length);
  for (let c = 0; c < buffer.numberOfChannels; c++) {
    const channel = buffer.getChannelData(c);
    for (let i = 0; i < channel.length; i++) samples[i] += channel[i] / buffer.numberOfChannels;
  }
  return { samples, duration: decoded.duration };
}

/** Transcribe samples. Rejects with EngineError (or a RangeError for memory). */
export function transcribe(
  samples: Float32Array,
  duration: number,
  onProgress: SpeechProgress | null,
  signal?: AbortSignal,
): Promise<TranscriptSegment[]> {
  return new Promise((resolve, reject) => {
    let worker: Worker;
    try {
      // Self-hosted module worker (copied to public/engines at build time).
      worker = new Worker(`${window.location.origin}/engines/speech-worker.mjs`, { type: "module" });
    } catch {
      reject(new EngineError("The speech engine could not start in this browser."));
      return;
    }
    const loaded = new Map<string, { loaded: number; total: number | null }>();
    const finish = () => {
      worker.terminate();
      signal?.removeEventListener("abort", onAbort);
    };
    const onAbort = () => {
      finish();
      reject(new DOMException("Processing was cancelled.", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort);
    worker.onmessage = (event: MessageEvent) => {
      const msg = event.data as
        | { type: "progress"; stage: "loading"; file: string; loaded: number; total: number | null }
        | { type: "progress"; stage: "transcribing" }
        | { type: "result"; chunks: WhisperChunk[] }
        | { type: "error"; message: string; range: boolean };
      if (msg.type === "progress" && msg.stage === "loading") {
        loaded.set(msg.file, { loaded: msg.loaded, total: msg.total });
        const all = [...loaded.values()];
        const total = all.every((f) => f.total) ? all.reduce((s, f) => s + (f.total ?? 0), 0) : 0;
        const done = all.reduce((s, f) => s + f.loaded, 0);
        onProgress?.("loading", total > 0 ? Math.min(1, done / total) : null);
      } else if (msg.type === "progress") {
        onProgress?.("transcribing", null); // Whisper reports no reliable progress
      } else if (msg.type === "result") {
        finish();
        resolve(segmentsFromChunks(msg.chunks, duration));
      } else if (msg.type === "error") {
        finish();
        reject(msg.range ? new RangeError(msg.message) : new EngineError(msg.message));
      }
    };
    worker.onerror = () => {
      finish();
      reject(new EngineError("The speech engine stopped unexpectedly."));
    };
    // Transfer the samples instead of copying them.
    worker.postMessage(
      { type: "transcribe", model: SPEECH_MODEL, language: SPEECH_LANGUAGE, audio: samples },
      [samples.buffer],
    );
  });
}
