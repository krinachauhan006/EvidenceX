// Typed client for in-browser processing
// (backend/app/modules/processing/router.py, "browser-processing" routes).

import { API_BASE, apiFetch } from "@/lib/api/client";
import type { BrowserClaim, BrowserFailureCode } from "@/lib/browser-processing/payload";
import type { ProcessingStatusInfo } from "@/lib/types/processing";

const path = (caseId: string, evidenceId: string, action: string) =>
  `/api/cases/${caseId}/evidence/${evidenceId}/browser-processing/${action}`;

/** Take the item for this browser. 409 when it is completed (without force) or held elsewhere. */
export function claimForBrowser(caseId: string, evidenceId: string, force: boolean): Promise<BrowserClaim> {
  return apiFetch<BrowserClaim>(path(caseId, evidenceId, "claim"), {
    method: "POST",
    body: JSON.stringify({ force }),
  });
}

/** Keep the claim alive. 409 when it is no longer this browser's. */
export function browserHeartbeat(caseId: string, evidenceId: string, runNumber: number): Promise<null> {
  return apiFetch<null>(path(caseId, evidenceId, "heartbeat"), {
    method: "POST",
    body: JSON.stringify({ run_number: runNumber }),
  });
}

/** Submit an already-encoded result body (see encodeResultBody). */
export function submitBrowserResult(
  caseId: string,
  evidenceId: string,
  body: string,
): Promise<ProcessingStatusInfo> {
  return apiFetch<ProcessingStatusInfo>(path(caseId, evidenceId, "result"), {
    method: "POST",
    body,
  });
}

export function reportBrowserFailure(
  caseId: string,
  evidenceId: string,
  runNumber: number,
  code: BrowserFailureCode,
): Promise<ProcessingStatusInfo> {
  return apiFetch<ProcessingStatusInfo>(path(caseId, evidenceId, "failure"), {
    method: "POST",
    body: JSON.stringify({ run_number: runNumber, code }),
  });
}

/**
 * Best-effort report while the page is being closed (`keepalive` lets the request
 * outlive the page). If it never arrives, the claim expires on its own after the
 * stale time, and the item can be processed again.
 */
export function reportInterruptedOnUnload(caseId: string, evidenceId: string, runNumber: number): void {
  try {
    void fetch(`${API_BASE}${path(caseId, evidenceId, "failure")}`, {
      method: "POST",
      keepalive: true,
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_number: runNumber, code: "interrupted" }),
    }).catch(() => undefined);
  } catch {
    /* the page is going away; the stale timeout covers it */
  }
}
