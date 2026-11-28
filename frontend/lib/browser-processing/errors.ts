// Errors raised while processing in the browser, and how each is reported to the
// server. Pure (unit-tested).

import type { BrowserFailureCode } from "./payload";

/** The browser could not decode the file (not proof that the file is damaged). */
export class MediaDecodeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MediaDecodeError";
  }
}

/** The engine (WASM, model or worker) could not be loaded or run. */
export class EngineError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EngineError";
  }
}

/** Not processable in this browser; detected BEFORE claiming, so nothing is recorded. */
export class NotProcessableHere extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NotProcessableHere";
  }
}

const MEMORY = /out of memory|memory access out of bounds|allocation failed|array buffer allocation|could not allocate|cannot enlarge memory/i;

export function isOutOfMemory(err: unknown): boolean {
  if (err instanceof RangeError) return true;
  const message = err instanceof Error ? err.message : typeof err === "string" ? err : "";
  return MEMORY.test(message);
}

export function failureCode(err: unknown): BrowserFailureCode {
  if (err instanceof DOMException && err.name === "AbortError") return "interrupted";
  if (isOutOfMemory(err)) return "browser_out_of_memory";
  if (err instanceof MediaDecodeError) return "browser_decode_failed";
  return "browser_engine_failed";
}

/** A short message for the person processing; never includes evidence content. */
export function userMessage(code: BrowserFailureCode): string {
  switch (code) {
    case "interrupted":
      return "Processing was stopped before it finished. Nothing was saved.";
    case "browser_out_of_memory":
      return "This device ran out of memory. Try a desktop computer, or a processing worker.";
    case "browser_decode_failed":
      return "This browser could not decode the file. Try Chrome or Edge, or a processing worker.";
    default:
      return "The in-browser engine could not run here. Try again, or use a current desktop browser.";
  }
}
