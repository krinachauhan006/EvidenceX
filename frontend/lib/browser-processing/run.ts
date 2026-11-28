// In-browser processing of one evidence file, end to end:
//
//   check this browser -> download the stored file -> verify its SHA-256 -> claim the
//   item on the server -> run the engine locally -> submit -> server validates and saves
//
// Nothing is claimed until the browser is known to be able to try, so an unsupported
// device leaves the item untouched. While the engine runs, a heartbeat keeps the claim
// alive; if the tab closes, a best-effort "interrupted" report is sent and otherwise
// the claim simply expires. The caller shows "Completed" only from the status the
// server returns after it committed the run.

import {
  browserHeartbeat,
  claimForBrowser,
  reportBrowserFailure,
  reportInterruptedOnUnload,
  submitBrowserResult,
} from "@/lib/api/browser-processing";
import { ApiError } from "@/lib/api/client";
import { fetchEvidenceBlob } from "@/lib/api/evidence";
import type { Evidence } from "@/lib/types/evidence";
import type { ProcessingStatusInfo } from "@/lib/types/processing";
import { assessSupport, probeEnvironment, type BrowserKind } from "./capabilities";
import { NotProcessableHere, failureCode, userMessage } from "./errors";
import { canDecodeVideoPicture, drawImage, mediaDuration, sampleFrames } from "./media";
import { OCR_ENGINE_VERSION, OCR_LANGUAGE, recognizeCanvas, releaseOcr } from "./ocr-engine";
import {
  encodeResultBody,
  sha256Hex,
  type BrowserClaim,
  type BrowserResult,
  type BrowserResultBody,
  type VideoFrame,
} from "./payload";
import {
  SPEECH_ENGINE_VERSION,
  SPEECH_LANGUAGE,
  SPEECH_MODEL,
  decodeToMono16k,
  transcribe,
} from "./speech-engine";
import { frameSchedule } from "./transcript";

// Longest recording processed in a browser (decoded samples and CPU time stay
// reasonable on a laptop). Longer files need a processing worker.
export const BROWSER_MAX_MEDIA_SECONDS = 600;

export type Phase =
  | "checking"
  | "downloading"
  | "claiming"
  | "loading-engine"
  | "recognizing"
  | "transcribing"
  | "sampling"
  | "saving";

export interface Progress {
  phase: Phase;
  /** 0..1 when the engine reports it reliably, otherwise null. */
  fraction: number | null;
  detail?: string;
}

export class BrowserProcessingError extends Error {
  /** True when nothing was claimed or recorded (the item is unchanged). */
  readonly untouched: boolean;
  constructor(message: string, untouched: boolean) {
    super(message);
    this.name = "BrowserProcessingError";
    this.untouched = untouched;
  }
}

function kindOf(evidence: Evidence): BrowserKind {
  if (evidence.evidence_type === "image" || evidence.evidence_type === "audio" || evidence.evidence_type === "video") {
    return evidence.evidence_type;
  }
  throw new NotProcessableHere("This file type is not processed in the browser.");
}

function detail(err: unknown, fallback: string): string {
  return err instanceof ApiError && typeof err.detail === "string" ? err.detail : fallback;
}

async function runEngine(
  kind: BrowserKind,
  blob: Blob,
  data: ArrayBuffer,
  claim: BrowserClaim,
  onProgress: (p: Progress) => void,
  signal: AbortSignal,
): Promise<{ result: BrowserResult; engine: BrowserResultBody["engine"] }> {
  if (kind === "image") {
    const drawn = await drawImage(blob);
    onProgress({ phase: "loading-engine", fraction: null, detail: "OCR engine (about 7 MB the first time)" });
    const lines = await recognizeCanvas(drawn.canvas, drawn.width, drawn.height, drawn.scale, (stage, f) =>
      onProgress(stage === "loading" ? { phase: "loading-engine", fraction: f } : { phase: "recognizing", fraction: f }),
    );
    return {
      result: { kind: "image", width: drawn.width, height: drawn.height, language: OCR_LANGUAGE, lines },
      engine: { ocr_engine_version: OCR_ENGINE_VERSION, device: "wasm" },
    };
  }

  if (kind === "audio") {
    const { samples, duration } = await decodeToMono16k(data);
    onProgress({ phase: "loading-engine", fraction: null, detail: "speech model (about 70 MB the first time)" });
    const segments = await transcribe(
      samples,
      duration,
      (stage, f) =>
        onProgress(stage === "loading" ? { phase: "loading-engine", fraction: f } : { phase: "transcribing", fraction: null }),
      signal,
    );
    return {
      result: { kind: "audio", duration_seconds: duration, language: SPEECH_LANGUAGE, segments },
      engine: { speech_engine_version: SPEECH_ENGINE_VERSION, speech_model: SPEECH_MODEL, device: "wasm" },
    };
  }

  // video: bounded frame sampling + OCR, then the soundtrack if this browser can decode it
  const duration = await mediaDuration(blob, "video");
  const { times, interval } = frameSchedule(
    duration,
    claim.limits.video_frame_interval_seconds,
    claim.limits.video_max_frames,
  );
  const frames: VideoFrame[] = [];
  const size = await sampleFrames(
    blob,
    times,
    async ({ t, canvas }, index) => {
      onProgress({ phase: "sampling", fraction: index / times.length, detail: `frame ${index + 1} of ${times.length}` });
      const lines = await recognizeCanvas(canvas, canvas.width, canvas.height, 1, null);
      frames.push({ t, sampling: index === 0 ? "first_frame" : "interval", lines });
    },
    signal,
  );
  await releaseOcr();
  let soundtrack: "transcribed" | "not_transcribed" = "not_transcribed";
  let transcript: Awaited<ReturnType<typeof transcribe>> = [];
  try {
    const { samples } = await decodeToMono16k(data);
    onProgress({ phase: "loading-engine", fraction: null, detail: "speech model (about 70 MB the first time)" });
    transcript = await transcribe(
      samples,
      duration,
      (stage, f) =>
        onProgress(stage === "loading" ? { phase: "loading-engine", fraction: f } : { phase: "transcribing", fraction: null }),
      signal,
    );
    soundtrack = "transcribed";
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    // No decodable soundtrack here: reported as "not transcribed", never as "no speech".
  }
  return {
    result: {
      kind: "video",
      duration_seconds: duration,
      frame_width: size.width,
      frame_height: size.height,
      interval_seconds: interval,
      ocr_language: OCR_LANGUAGE,
      frames,
      soundtrack,
      transcript_language: soundtrack === "transcribed" ? SPEECH_LANGUAGE : null,
      transcript,
    },
    engine: {
      ocr_engine_version: OCR_ENGINE_VERSION,
      speech_engine_version: soundtrack === "transcribed" ? SPEECH_ENGINE_VERSION : null,
      speech_model: soundtrack === "transcribed" ? SPEECH_MODEL : null,
      device: "wasm",
    },
  };
}

export interface RunOptions {
  caseId: string;
  evidence: Evidence;
  force: boolean;
  onProgress: (p: Progress) => void;
  signal: AbortSignal;
}

export async function processInBrowser({
  caseId,
  evidence,
  force,
  onProgress,
  signal,
}: RunOptions): Promise<ProcessingStatusInfo> {
  // 1. Before anything is claimed: can this browser do it at all?
  onProgress({ phase: "checking", fraction: null });
  let kind: BrowserKind;
  let blob: Blob;
  let data: ArrayBuffer;
  try {
    kind = kindOf(evidence);
    const support = assessSupport(kind, probeEnvironment(evidence.mime_type));
    if (!support.supported) throw new NotProcessableHere(support.reason ?? "Not supported in this browser.");
    onProgress({ phase: "downloading", fraction: null });
    blob = await fetchEvidenceBlob(caseId, evidence.id, signal);
    data = await blob.arrayBuffer();
    if ((await sha256Hex(data)) !== evidence.sha256) {
      throw new NotProcessableHere("The downloaded file does not match the stored file. Reload and try again.");
    }
    if (kind === "video" && !(await canDecodeVideoPicture(blob))) {
      throw new NotProcessableHere(
        "This browser cannot decode this video's picture (its codec is not supported here). Nothing was changed. Try another browser, or use a processing worker.",
      );
    }
    if (kind !== "image") {
      const seconds = await mediaDuration(blob, kind);
      if (seconds > BROWSER_MAX_MEDIA_SECONDS) {
        throw new NotProcessableHere(
          `This recording is longer than ${BROWSER_MAX_MEDIA_SECONDS / 60} minutes, too long to process in a browser. Use a processing worker.`,
        );
      }
    }
  } catch (err) {
    if (err instanceof NotProcessableHere) throw new BrowserProcessingError(err.message, true);
    if (err instanceof DOMException && err.name === "AbortError") throw new BrowserProcessingError("Cancelled.", true);
    const code = failureCode(err);
    throw new BrowserProcessingError(userMessage(code === "interrupted" ? "browser_engine_failed" : code), true);
  }

  // 2. Claim. From here on the server knows this browser is working on the item.
  onProgress({ phase: "claiming", fraction: null });
  let claim: BrowserClaim;
  try {
    claim = await claimForBrowser(caseId, evidence.id, force);
  } catch (err) {
    throw new BrowserProcessingError(detail(err, "The item could not be claimed for processing."), true);
  }
  const run = claim.run_number;
  const lost = new AbortController();
  const stop = () => lost.abort();
  signal.addEventListener("abort", stop);
  const beat = window.setInterval(() => {
    browserHeartbeat(caseId, evidence.id, run).catch((err) => {
      if (err instanceof ApiError && err.status === 409) lost.abort(); // taken over
    });
  }, claim.heartbeat_seconds * 1000);
  const onPageHide = () => reportInterruptedOnUnload(caseId, evidence.id, run);
  window.addEventListener("pagehide", onPageHide);
  const started = performance.now();

  try {
    // 3. Run the engine on this device.
    let output: Awaited<ReturnType<typeof runEngine>>;
    try {
      output = await runEngine(kind, blob, data, claim, onProgress, lost.signal);
    } catch (err) {
      const code = failureCode(err);
      await reportBrowserFailure(caseId, evidence.id, run, code).catch(() => undefined);
      throw new BrowserProcessingError(userMessage(code), false);
    }

    // 4. Submit. Completed only once the server has validated and committed the run.
    onProgress({ phase: "saving", fraction: null });
    const body = encodeResultBody({
      run_number: run,
      source_sha256: claim.sha256,
      duration_ms: Math.round(performance.now() - started),
      engine: output.engine,
      result: output.result,
    });
    if (body === null) {
      await reportBrowserFailure(caseId, evidence.id, run, "browser_engine_failed").catch(() => undefined);
      throw new BrowserProcessingError(
        "The result is too large to submit from a browser. Use a processing worker for this file.",
        false,
      );
    }
    try {
      return await submitBrowserResult(caseId, evidence.id, body);
    } catch (err) {
      if (!(err instanceof ApiError)) {
        // Network failure: the server may never have seen the result. Say so, so the
        // item does not wait for the stale timeout.
        await reportBrowserFailure(caseId, evidence.id, run, "interrupted").catch(() => undefined);
      }
      // 400: the server refused the result and recorded why. 409: no longer ours.
      throw new BrowserProcessingError(detail(err, "The result could not be saved."), false);
    }
  } finally {
    window.clearInterval(beat);
    window.removeEventListener("pagehide", onPageHide);
    signal.removeEventListener("abort", stop);
    await releaseOcr();
  }
}
