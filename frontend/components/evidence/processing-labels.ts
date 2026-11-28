// Human-readable labels for backend processing codes.

import type { ExtractionOutcome, SkipReason } from "@/lib/types/processing";

const ERROR_CODE_LABELS: Record<string, string> = {
  corrupt_file: "Corrupt or unreadable file",
  password_required: "Password required",
  unsupported_content: "Unsupported content",
  dependency_missing: "Required component missing",
  model_unavailable: "Model unavailable",
  limit_exceeded: "Limit exceeded",
  timeout: "Timed out",
  storage_missing: "Stored file missing",
  internal_error: "Internal error",
  model_invalid: "Speech model damaged",
  resource_exhausted: "Not enough memory",
  model_init_failed: "Speech model failed to start",
  interrupted: "Interrupted before finishing",
  browser_engine_failed: "The in-browser engine could not run on that device",
  browser_decode_failed: "That browser could not decode the file",
  browser_out_of_memory: "The device ran out of memory",
  browser_result_rejected: "The browser's result was refused by the server",
};

// Failures that say nothing about the file: the external worker retries these by itself
// (app/worker.py RECOVERABLE_CODES).
const WORKER_RETRIED_CODES = new Set([
  "dependency_missing",
  "interrupted",
  "browser_engine_failed",
  "browser_decode_failed",
  "browser_out_of_memory",
]);

export function errorCodeLabel(code: string | null | undefined): string | null {
  if (!code) return null;
  return ERROR_CODE_LABELS[code] ?? code;
}

const OUTCOME_LABELS: Record<ExtractionOutcome, string> = {
  ok: "Complete",
  partial: "Partial",
  needs_ocr: "Requires OCR",
  empty: "No extractable content",
};

export function outcomeLabel(outcome: ExtractionOutcome | null | undefined): string | null {
  return outcome ? OUTCOME_LABELS[outcome] : null;
}

const SKIP_REASON_TEXT: Record<SkipReason, string> = {
  already_completed: "already processed",
  already_processing: "already processing",
  no_extractor: "no extractor is available for this file type yet",
  external_worker: "waiting for the processing worker (this file type is processed separately)",
};

export function skipReasonText(reason: SkipReason): string {
  return SKIP_REASON_TEXT[reason] ?? reason;
}

/**
 * True when the item is waiting for the external processing worker rather than for
 * this server: a pending item of an external file type, or one that failed earlier
 * only because an engine was missing or was interrupted (the worker recovers those).
 */
export function awaitingWorker(
  status: string,
  externalWorker: boolean | null | undefined,
  errorCode: string | null | undefined,
): boolean {
  if (!externalWorker) return false;
  return (
    status === "pending" ||
    (status === "failed" && errorCode != null && WORKER_RETRIED_CODES.has(errorCode))
  );
}
