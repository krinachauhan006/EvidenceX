// What this browser can do for in-browser processing, decided BEFORE anything is
// claimed on the server, so an unsupported device never marks evidence as failed.
//
// Pure: the caller passes a probe of the environment (see `probeEnvironment`), so the
// rules are unit-tested without a browser (tests/browser-processing.test.mjs).
//
// WebGPU is NOT required. OCR (Tesseract.js) and speech (Whisper via Transformers.js)
// both run on WebAssembly on the CPU. WebGPU is only reported, for information.

export type BrowserKind = "image" | "audio" | "video";

export interface EnvironmentProbe {
  webAssembly: boolean;
  /** WebAssembly SIMD (needed by the speech engine's WASM build). */
  wasmSimd: boolean;
  worker: boolean;
  /** document.createElement("canvas").getContext("2d") works. */
  canvas2d: boolean;
  createImageBitmap: boolean;
  /** AudioContext / webkitAudioContext exists (decodes audio to samples). */
  audioContext: boolean;
  /** crypto.subtle.digest exists (secure context: https or localhost). */
  subtleCrypto: boolean;
  /** navigator.gpu exists. Informational only. */
  webGpu: boolean;
  /** navigator.deviceMemory in GB, when the browser reports it. */
  deviceMemoryGb: number | null;
  /** HTMLVideoElement.canPlayType for the evidence MIME type ("", "maybe", "probably"). */
  canPlayVideo: string;
  canPlayAudio: string;
}

export interface Support {
  supported: boolean;
  /** Why not (shown to the user), when unsupported. */
  reason: string | null;
  /** Things worth knowing that do not block processing. */
  notes: string[];
}

// Below this, Whisper plus the decoded recording may not fit in memory.
const LOW_MEMORY_GB = 4;

export function assessSupport(kind: BrowserKind, env: EnvironmentProbe): Support {
  const notes: string[] = [];
  const no = (reason: string): Support => ({ supported: false, reason, notes });

  if (!env.webAssembly) return no("This browser does not support WebAssembly.");
  if (!env.worker) return no("This browser does not support Web Workers.");
  if (!env.subtleCrypto) {
    return no("In-browser processing needs a secure (https) connection to verify the file.");
  }
  if (kind === "image" || kind === "video") {
    if (!env.canvas2d || !env.createImageBitmap) {
      return no("This browser cannot draw images for OCR.");
    }
  }
  if (kind === "video" && env.canPlayVideo === "") {
    return no("This browser cannot decode this video format. Try Chrome or Edge.");
  }
  if (kind === "audio") {
    if (!env.audioContext) return no("This browser cannot decode audio (no Web Audio).");
    if (!env.wasmSimd) return no("The speech engine needs WebAssembly SIMD, which this browser lacks.");
    if (env.canPlayAudio === "") {
      return no("This browser cannot decode this audio format. Try Chrome or Edge.");
    }
  }
  if (kind === "video" && (!env.audioContext || !env.wasmSimd)) {
    notes.push("The soundtrack cannot be transcribed in this browser; only frames will be read.");
  }
  if ((kind === "audio" || kind === "video") && env.deviceMemoryGb !== null && env.deviceMemoryGb < LOW_MEMORY_GB) {
    notes.push("This device reports little memory; long recordings may fail.");
  }
  if (!env.webGpu) {
    notes.push("WebGPU is not available; the engines run on the CPU (WebAssembly), which is slower.");
  }
  return { supported: true, reason: null, notes };
}

// A tiny WebAssembly module that uses SIMD instructions (i8x16.splat, i8x16.popcnt);
// the same probe as the wasm-feature-detect library. Valid only where SIMD is supported.
export const SIMD_PROBE = new Uint8Array([
  0, 97, 115, 109, 1, 0, 0, 0, 1, 5, 1, 96, 0, 1, 123, 3, 2, 1, 0, 10, 10, 1, 8, 0, 65, 0, 253, 15,
  253, 98, 11,
]);

/** Probe the real browser. Never throws. */
export function probeEnvironment(mimeType: string): EnvironmentProbe {
  const g = globalThis as unknown as {
    WebAssembly?: { validate?: (b: BufferSource) => boolean };
    Worker?: unknown;
    createImageBitmap?: unknown;
    AudioContext?: unknown;
    webkitAudioContext?: unknown;
    crypto?: { subtle?: { digest?: unknown } };
    navigator?: { gpu?: unknown; deviceMemory?: number };
    document?: Document;
  };
  let canvas2d = false;
  let canPlayVideo = "";
  let canPlayAudio = "";
  try {
    const doc = g.document;
    if (doc) {
      canvas2d = Boolean(doc.createElement("canvas").getContext("2d"));
      if (mimeType.startsWith("video/")) canPlayVideo = doc.createElement("video").canPlayType(mimeType);
      if (mimeType.startsWith("audio/")) canPlayAudio = doc.createElement("audio").canPlayType(mimeType);
    }
  } catch {
    /* leave false/empty */
  }
  let wasmSimd = false;
  try {
    wasmSimd = Boolean(g.WebAssembly?.validate?.(SIMD_PROBE));
  } catch {
    wasmSimd = false;
  }
  const memory = g.navigator?.deviceMemory;
  return {
    webAssembly: typeof g.WebAssembly?.validate === "function",
    wasmSimd,
    worker: typeof g.Worker === "function",
    canvas2d,
    createImageBitmap: typeof g.createImageBitmap === "function",
    audioContext: typeof g.AudioContext === "function" || typeof g.webkitAudioContext === "function",
    subtleCrypto: typeof g.crypto?.subtle?.digest === "function",
    webGpu: Boolean(g.navigator?.gpu),
    deviceMemoryGb: typeof memory === "number" ? memory : null,
    canPlayVideo,
    canPlayAudio,
  };
}
