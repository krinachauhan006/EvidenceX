// Typed client for the processing endpoints
// (backend/app/modules/processing/router.py). Every path is scoped to a case.

import { apiFetch } from "@/lib/api/client";
import type {
  CaseProcessingSummary,
  Extraction,
  ExtractionList,
  ProcessAccepted,
  ProcessingStatusInfo,
  SegmentList,
  SegmentQuery,
} from "@/lib/types/processing";

const evidencePath = (caseId: string, evidenceId: string) =>
  `/api/cases/${caseId}/evidence/${evidenceId}`;

// --- queue work (202 Accepted; extraction runs in the background) ---------------

/**
 * Queue one item. `force: true` on a completed item creates a NEW extraction run;
 * earlier runs are kept.
 */
export function processEvidence(
  caseId: string,
  evidenceId: string,
  options: { force?: boolean; audioModel?: string } = {},
): Promise<ProcessAccepted> {
  const body: { force: boolean; audio_model?: string } = { force: options.force ?? false };
  // Only available local models are accepted; the server answers 400 otherwise and
  // never substitutes another model.
  if (options.audioModel) body.audio_model = options.audioModel;
  return apiFetch<ProcessAccepted>(`${evidencePath(caseId, evidenceId)}/process`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Queue every `pending` item in the case that has an extractor. */
export function processPending(caseId: string): Promise<ProcessAccepted> {
  return apiFetch<ProcessAccepted>(`/api/cases/${caseId}/evidence/process-pending`, {
    method: "POST",
  });
}

/** Queue a `failed` item again (the server answers 409 for any other status). */
export function retryEvidence(caseId: string, evidenceId: string): Promise<ProcessAccepted> {
  return apiFetch<ProcessAccepted>(`${evidencePath(caseId, evidenceId)}/retry`, {
    method: "POST",
  });
}

// --- read status and results -----------------------------------------------------

export function getCaseProcessing(
  caseId: string,
  signal?: AbortSignal,
): Promise<CaseProcessingSummary> {
  return apiFetch<CaseProcessingSummary>(`/api/cases/${caseId}/processing`, { signal });
}

export function getProcessingStatus(
  caseId: string,
  evidenceId: string,
  signal?: AbortSignal,
): Promise<ProcessingStatusInfo> {
  return apiFetch<ProcessingStatusInfo>(`${evidencePath(caseId, evidenceId)}/processing`, {
    signal,
  });
}

/** The current run. 404 when the item has no successful run yet. */
export function getCurrentExtraction(
  caseId: string,
  evidenceId: string,
  signal?: AbortSignal,
): Promise<Extraction> {
  return apiFetch<Extraction>(`${evidencePath(caseId, evidenceId)}/extraction`, { signal });
}

/** Run history, newest first. Includes failed runs. */
export function listExtractions(
  caseId: string,
  evidenceId: string,
  signal?: AbortSignal,
): Promise<ExtractionList> {
  return apiFetch<ExtractionList>(`${evidencePath(caseId, evidenceId)}/extractions`, {
    signal,
  });
}

export function getExtraction(
  caseId: string,
  evidenceId: string,
  extractionId: string,
  signal?: AbortSignal,
): Promise<Extraction> {
  return apiFetch<Extraction>(
    `${evidencePath(caseId, evidenceId)}/extractions/${extractionId}`,
    { signal },
  );
}

/** Segments of one run (the current run when `extractionId` is omitted). */
export function listSegments(
  caseId: string,
  evidenceId: string,
  query: SegmentQuery = {},
  signal?: AbortSignal,
): Promise<SegmentList> {
  const params = new URLSearchParams();
  if (query.extractionId) params.set("extraction_id", query.extractionId);
  if (query.page != null) params.set("page", String(query.page));
  if (query.segmentType) params.set("segment_type", query.segmentType);
  if (query.limit != null) params.set("limit", String(query.limit));
  if (query.offset != null) params.set("offset", String(query.offset));
  const qs = params.toString();
  return apiFetch<SegmentList>(
    `${evidencePath(caseId, evidenceId)}/segments${qs ? `?${qs}` : ""}`,
    { signal },
  );
}
