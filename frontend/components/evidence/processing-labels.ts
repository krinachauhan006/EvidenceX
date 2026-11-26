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
};

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
};

export function skipReasonText(reason: SkipReason): string {
  return SKIP_REASON_TEXT[reason] ?? reason;
}
