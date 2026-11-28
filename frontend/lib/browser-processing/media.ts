// Decoding in the browser: images to a canvas, recordings' durations, and bounded
// video frame sampling. Every object URL and element is released afterwards.

import { MediaDecodeError } from "./errors";

// Longest side of the canvas given to OCR. Larger images are scaled down (boxes are
// mapped back to the original pixels), which bounds memory to ~64 MB per canvas.
export const MAX_OCR_SIDE = 4096;
// Longest side of a sampled video frame.
export const MAX_FRAME_SIDE = 1920;
const SEEK_TIMEOUT_MS = 15_000;

export interface DrawnImage {
  canvas: HTMLCanvasElement;
  /** Size of the image as displayed (EXIF orientation applied). */
  width: number;
  height: number;
  /** canvas size / image size. */
  scale: number;
}

function canvasOf(width: number, height: number): { canvas: HTMLCanvasElement; ctx: CanvasRenderingContext2D } {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) throw new MediaDecodeError("A drawing surface could not be created.");
  return { canvas, ctx };
}

/** Decode an image with its EXIF orientation applied, as the server measures it. */
export async function drawImage(blob: Blob): Promise<DrawnImage> {
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(blob, { imageOrientation: "from-image" });
  } catch {
    throw new MediaDecodeError("The image could not be decoded by this browser.");
  }
  try {
    const { width, height } = bitmap;
    const scale = Math.min(1, MAX_OCR_SIDE / Math.max(width, height));
    const { canvas, ctx } = canvasOf(Math.round(width * scale), Math.round(height * scale));
    ctx.fillStyle = "#ffffff"; // transparent areas read as white paper, as on the server
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    return { canvas, width, height, scale };
  } finally {
    bitmap.close();
  }
}

function once(target: EventTarget, ok: string, timeoutMs: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => done(new MediaDecodeError("The media did not respond in time.")), timeoutMs);
    const onOk = () => done(null);
    const onErr = () => done(new MediaDecodeError("The media could not be decoded by this browser."));
    function done(err: Error | null) {
      clearTimeout(timer);
      target.removeEventListener(ok, onOk);
      target.removeEventListener("error", onErr);
      if (err) reject(err);
      else resolve();
    }
    target.addEventListener(ok, onOk);
    target.addEventListener("error", onErr);
  });
}

/** Duration in seconds from the media element's metadata (no full decode). */
export async function mediaDuration(blob: Blob, kind: "audio" | "video"): Promise<number> {
  const url = URL.createObjectURL(blob);
  const el = document.createElement(kind);
  el.preload = "metadata";
  el.muted = true;
  try {
    const ready = once(el, "loadedmetadata", SEEK_TIMEOUT_MS);
    el.src = url;
    await ready;
    let duration = el.duration;
    if (!Number.isFinite(duration)) {
      // Some WebM files omit the duration: seeking far ahead makes the browser find it.
      const seeked = once(el, "durationchange", SEEK_TIMEOUT_MS);
      el.currentTime = 1e9;
      await seeked;
      duration = el.duration;
    }
    if (!Number.isFinite(duration) || duration <= 0) {
      throw new MediaDecodeError("The recording's length could not be read by this browser.");
    }
    return duration;
  } finally {
    el.removeAttribute("src");
    el.load();
    URL.revokeObjectURL(url);
  }
}

/**
 * Whether this browser can decode the video's PICTURE (not only its container): the
 * first frame must decode. A container the browser recognises can still hold a codec
 * it cannot play (for example MPEG-4 Part 2 in Chrome and Edge). Checked before the
 * item is claimed, so an unsupported codec changes nothing on the server.
 */
export async function canDecodeVideoPicture(blob: Blob): Promise<boolean> {
  const url = URL.createObjectURL(blob);
  const video = document.createElement("video");
  video.preload = "auto";
  video.muted = true;
  try {
    const ready = once(video, "loadeddata", SEEK_TIMEOUT_MS);
    video.src = url;
    await ready;
    return video.videoWidth > 0 && video.videoHeight > 0;
  } catch {
    return false;
  } finally {
    video.removeAttribute("src");
    video.load();
    URL.revokeObjectURL(url);
  }
}

export interface SampledFrame {
  /** The time the browser actually decoded (may differ slightly from the request). */
  t: number;
  canvas: HTMLCanvasElement;
}

/**
 * Decode the frames at `times`, one at a time (only one frame is held in memory), and
 * hand each to `onFrame` before the next is decoded. Frames whose decoded time is not
 * later than the previous one are skipped.
 */
export async function sampleFrames(
  blob: Blob,
  times: readonly number[],
  onFrame: (frame: SampledFrame, index: number) => Promise<void>,
  signal?: AbortSignal,
): Promise<{ width: number; height: number }> {
  const url = URL.createObjectURL(blob);
  const video = document.createElement("video");
  video.preload = "auto";
  video.muted = true;
  video.playsInline = true;
  try {
    const ready = once(video, "loadeddata", SEEK_TIMEOUT_MS);
    video.src = url;
    await ready;
    const vw = video.videoWidth;
    const vh = video.videoHeight;
    if (!vw || !vh) throw new MediaDecodeError("The video has no decodable picture in this browser.");
    const scale = Math.min(1, MAX_FRAME_SIDE / Math.max(vw, vh));
    const width = Math.round(vw * scale);
    const height = Math.round(vh * scale);
    const { canvas, ctx } = canvasOf(width, height);
    let previous = -1;
    for (let i = 0; i < times.length; i++) {
      if (signal?.aborted) throw new DOMException("Processing was cancelled.", "AbortError");
      const seeked = once(video, "seeked", SEEK_TIMEOUT_MS);
      video.currentTime = times[i];
      await seeked;
      const t = Math.round(video.currentTime * 1000) / 1000;
      if (t <= previous) continue;
      previous = t;
      ctx.drawImage(video, 0, 0, width, height);
      await onFrame({ t, canvas }, i);
    }
    return { width, height };
  } finally {
    video.removeAttribute("src");
    video.load();
    URL.revokeObjectURL(url);
  }
}
