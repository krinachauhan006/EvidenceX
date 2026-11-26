// Typed client for the Phase 2 endpoints (backend/app/modules/analysis/router_phase2.py):
// events, timeline, search, grounded questions, reports, graph exports and audit checks.

import { apiBlob, apiFetch } from "@/lib/api/client";
import type {
  AiStatus,
  AskResult,
  AuditVerification,
  EventAction,
  EventDetail,
  InvestigationEvent,
  OcrLanguages,
  Report,
  SearchResult,
  Timeline,
  WorkspaceSummary,
} from "@/lib/types/phase2";

const base = (caseId: string) => `/api/cases/${caseId}`;
const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

// --- events ---------------------------------------------------------------------------

export function listEvents(
  caseId: string,
  q: { status?: string; eventType?: string } = {},
  signal?: AbortSignal,
): Promise<{ items: InvestigationEvent[]; total: number }> {
  return apiFetch(
    `${base(caseId)}/events${query({ status: q.status, event_type: q.eventType })}`,
    { signal },
  );
}

export function getEvent(caseId: string, eventId: string, signal?: AbortSignal) {
  return apiFetch<EventDetail>(`${base(caseId)}/events/${eventId}`, { signal });
}

export function reviewEvent(
  caseId: string,
  eventId: string,
  body: { action: EventAction; note?: string; claim_id?: string; claim_ids?: string[] },
): Promise<EventDetail> {
  return apiFetch<EventDetail>(`${base(caseId)}/events/${eventId}/review`, post(body));
}

export function createEvent(
  caseId: string,
  body: { title: string; event_type: string; claim_ids: string[]; note?: string },
): Promise<EventDetail> {
  return apiFetch<EventDetail>(`${base(caseId)}/events`, post(body));
}

export function proposeEvents(caseId: string): Promise<{ created: number }> {
  return apiFetch(`${base(caseId)}/events/propose`, { method: "POST" });
}

// --- timeline -------------------------------------------------------------------------

export function getTimeline(
  caseId: string,
  q: {
    evidenceId?: string;
    entityId?: string;
    eventId?: string;
    reviewStatus?: string;
    modality?: string;
    dateFrom?: string;
    dateTo?: string;
  } = {},
  signal?: AbortSignal,
): Promise<Timeline> {
  return apiFetch<Timeline>(
    `${base(caseId)}/timeline${query({
      evidence_id: q.evidenceId,
      entity_id: q.entityId,
      event_id: q.eventId,
      review_status: q.reviewStatus,
      modality: q.modality,
      date_from: q.dateFrom,
      date_to: q.dateTo,
    })}`,
    { signal },
  );
}

// --- search and questions ---------------------------------------------------------------

export function searchCase(
  caseId: string,
  q: string,
  filters: { kinds?: string[]; modality?: string; reviewStatus?: string; limit?: number } = {},
  signal?: AbortSignal,
): Promise<SearchResult> {
  return apiFetch<SearchResult>(
    `${base(caseId)}/search${query({
      q,
      kinds: filters.kinds?.length ? filters.kinds.join(",") : undefined,
      modality: filters.modality,
      review_status: filters.reviewStatus,
      limit: filters.limit,
    })}`,
    { signal },
  );
}

export function askCase(caseId: string, question: string): Promise<AskResult> {
  return apiFetch<AskResult>(`${base(caseId)}/ask`, post({ question }));
}

export function aiStatus(signal?: AbortSignal): Promise<AiStatus> {
  return apiFetch<AiStatus>(`/api/ai/status`, { signal });
}

// --- reports and exports ----------------------------------------------------------------

export function listReports(caseId: string, signal?: AbortSignal) {
  return apiFetch<{ items: Report[]; total: number }>(`${base(caseId)}/reports`, { signal });
}

export function createReport(
  caseId: string,
  body: { kind: "investigation" | "graph"; include_ai_summary?: boolean; entity_type?: string },
): Promise<Report> {
  return apiFetch<Report>(`${base(caseId)}/reports`, post(body));
}

export function reportPdf(caseId: string, reportId: string, signal?: AbortSignal): Promise<Blob> {
  return apiBlob(`${base(caseId)}/reports/${reportId}/download?inline=true`, signal);
}

export function graphExport(
  caseId: string,
  format: "json" | "graphml",
  q: { entityType?: string; includeClaims?: boolean } = {},
): Promise<Blob> {
  return apiBlob(
    `${base(caseId)}/graph/export${query({
      format,
      entity_type: q.entityType,
      include_claims: q.includeClaims,
    })}`,
  );
}

// --- audit, workspace, OCR --------------------------------------------------------------

export function verifyAudit(caseId: string, signal?: AbortSignal): Promise<AuditVerification> {
  return apiFetch<AuditVerification>(`${base(caseId)}/reviews/verify`, { signal });
}

export function workspaceSummary(signal?: AbortSignal): Promise<WorkspaceSummary> {
  return apiFetch<WorkspaceSummary>(`/api/workspace/summary`, { signal });
}

export function ocrLanguages(signal?: AbortSignal): Promise<OcrLanguages> {
  return apiFetch<OcrLanguages>(`/api/ocr/languages`, { signal });
}
