// Tesseract.js, loaded only when an image or video is processed (dynamic import, so
// it is not part of the initial page bundle). Every engine file is served by this
// web app itself from /engines/tesseract (copied from node_modules at build time by
// scripts/copy-browser-engines.mjs): no CDN, and evidence never leaves the browser.
// The English language data (~3 MB) is cached by Tesseract.js in IndexedDB.

import { EngineError } from "./errors";
import { linesFromBlocks, type OcrLine, type TesseractBlock } from "./ocr-lines";

export const OCR_ENGINE_VERSION = "7.0.0"; // keep in step with package.json
export const OCR_LANGUAGE = "eng";

interface TesseractWorker {
  recognize(
    image: HTMLCanvasElement,
    options?: Record<string, unknown>,
    output?: Record<string, boolean>,
  ): Promise<{ data: { blocks: TesseractBlock[] | null } }>;
  terminate(): Promise<unknown>;
}

interface TesseractModule {
  createWorker(
    langs: string,
    oem: number,
    options: Record<string, unknown>,
  ): Promise<TesseractWorker>;
}

export type OcrProgress = (stage: "loading" | "recognizing", fraction: number | null) => void;

let current: { worker: TesseractWorker; onProgress: OcrProgress | null } | null = null;
let starting: Promise<TesseractWorker> | null = null;

function origin(): string {
  return window.location.origin;
}

async function getWorker(onProgress: OcrProgress | null): Promise<TesseractWorker> {
  if (current) {
    current.onProgress = onProgress;
    return current.worker;
  }
  if (!starting) {
    starting = (async () => {
      let mod: TesseractModule;
      try {
        mod = (await import("tesseract.js")) as unknown as TesseractModule;
      } catch {
        throw new EngineError("The OCR engine could not be loaded.");
      }
      const holder: { onProgress: OcrProgress | null } = { onProgress };
      const worker = await mod.createWorker(OCR_LANGUAGE, 1 /* LSTM only */, {
        workerPath: `${origin()}/engines/tesseract/worker.min.js`,
        corePath: `${origin()}/engines/tesseract/core`,
        langPath: `${origin()}/engines/tesseract/lang`,
        workerBlobURL: false,
        gzip: true,
        logger: (m: { status?: string; progress?: number }) => {
          const p = current?.onProgress ?? holder.onProgress;
          if (!p) return;
          if (m.status === "recognizing text") p("recognizing", m.progress ?? null);
          else p("loading", typeof m.progress === "number" ? m.progress : null);
        },
      });
      current = { worker, onProgress };
      return worker;
    })().finally(() => {
      starting = null;
    });
  }
  try {
    return await starting;
  } catch (err) {
    if (err instanceof EngineError) throw err;
    throw new EngineError("The OCR engine could not start in this browser.");
  }
}

/** OCR one canvas. Boxes refer to `width` x `height` (the canvas divided by `scale`). */
export async function recognizeCanvas(
  canvas: HTMLCanvasElement,
  width: number,
  height: number,
  scale: number,
  onProgress: OcrProgress | null,
): Promise<OcrLine[]> {
  const worker = await getWorker(onProgress);
  const { data } = await worker.recognize(canvas, {}, { blocks: true, text: false });
  return linesFromBlocks(data.blocks, width, height, scale);
}

/** Free the engine's memory (about 50-100 MB) when processing is done. */
export async function releaseOcr(): Promise<void> {
  const held = current;
  current = null;
  if (held) await held.worker.terminate().catch(() => undefined);
}
