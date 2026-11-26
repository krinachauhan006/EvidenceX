// Typed client for the analysis endpoints (backend/app/modules/analysis/router.py).
// Every path is scoped to a case.

import { apiBlob, apiFetch } from "@/lib/api/client";
import type {
  AnalysisRun,
  ClaimAction,
  ClaimDetail,
  ClaimList,
  ContradictionAction,
  ContradictionDetail,
  Dashboard,
  Entity,
  EntityAction,
  EntityDetail,
  EvidenceAnalysisSummary,
  Graph,
  Candidate,
  Contradiction,
  Relationship,
  ReviewAction,
  ReviewQueue,
  SegmentReviewList,
} from "@/lib/types/analysis";
import type { AudioModelList } from "@/lib/types/processing";

const base = (caseId: string) => `/api/cases/${caseId}`;

function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

// --- runs -------------------------------------------------------------------------

export function startAnalysis(caseId: string): Promise<AnalysisRun> {
  return apiFetch<AnalysisRun>(`${base(caseId)}/analysis`, { method: "POST" });
}

export function latestAnalysis(
  caseId: string,
  signal?: AbortSignal,
): Promise<{ run: AnalysisRun | null }> {
  return apiFetch(`${base(caseId)}/analysis/latest`, { signal });
}

// --- claims -----------------------------------------------------------------------

export interface ClaimQuery {
  evidenceId?: string;
  reviewStatus?: string;
  claimType?: string;
  modality?: string;
  entityId?: string;
  segmentId?: string;
  q?: string;
  includeSuperseded?: boolean;
  limit?: number;
  offset?: number;
}

export function listClaims(
  caseId: string,
  q: ClaimQuery = {},
  signal?: AbortSignal,
): Promise<ClaimList> {
  return apiFetch<ClaimList>(
    `${base(caseId)}/claims${query({
      evidence_id: q.evidenceId,
      review_status: q.reviewStatus,
      claim_type: q.claimType,
      modality: q.modality,
      entity_id: q.entityId,
      segment_id: q.segmentId,
      q: q.q,
      include_superseded: q.includeSuperseded,
      limit: q.limit,
      offset: q.offset,
    })}`,
    { signal },
  );
}

export function getClaim(caseId: string, claimId: string, signal?: AbortSignal) {
  return apiFetch<ClaimDetail>(`${base(caseId)}/claims/${claimId}`, { signal });
}

export function reviewClaim(
  caseId: string,
  claimId: string,
  body: { action: ClaimAction; note?: string; reviewer?: string; reviewed_text?: string },
): Promise<ClaimDetail> {
  return apiFetch<ClaimDetail>(`${base(caseId)}/claims/${claimId}/review`, post(body));
}

// --- entities ---------------------------------------------------------------------

export function listEntities(
  caseId: string,
  q: { entityType?: string; q?: string; includeMerged?: boolean } = {},
  signal?: AbortSignal,
): Promise<{ items: Entity[]; total: number }> {
  return apiFetch(
    `${base(caseId)}/entities${query({
      entity_type: q.entityType,
      q: q.q,
      include_merged: q.includeMerged,
    })}`,
    { signal },
  );
}

export function entityCandidates(caseId: string, signal?: AbortSignal) {
  return apiFetch<{ items: Candidate[]; total: number }>(
    `${base(caseId)}/entities/candidates`,
    { signal },
  );
}

export function getEntity(caseId: string, entityId: string, signal?: AbortSignal) {
  return apiFetch<EntityDetail>(`${base(caseId)}/entities/${entityId}`, { signal });
}

export function reviewEntity(
  caseId: string,
  entityId: string,
  body: { action: EntityAction; target_entity_id?: string; note?: string; reviewer?: string },
): Promise<EntityDetail> {
  return apiFetch<EntityDetail>(`${base(caseId)}/entities/${entityId}/review`, post(body));
}

// --- relationships ----------------------------------------------------------------

export function listRelationships(
  caseId: string,
  q: { relationType?: string; evidenceId?: string; claimId?: string } = {},
  signal?: AbortSignal,
): Promise<{ items: Relationship[]; total: number }> {
  return apiFetch(
    `${base(caseId)}/relationships${query({
      relation_type: q.relationType,
      evidence_id: q.evidenceId,
      claim_id: q.claimId,
    })}`,
    { signal },
  );
}

export function reviewRelationship(
  caseId: string,
  relationshipId: string,
  body: { action: "verify" | "reject" | "needs_verification" | "note"; note?: string },
): Promise<Relationship> {
  return apiFetch<Relationship>(
    `${base(caseId)}/relationships/${relationshipId}/review`,
    post(body),
  );
}

// --- potential contradictions -----------------------------------------------------

export function listContradictions(
  caseId: string,
  q: { reviewStatus?: string; severity?: string; evidenceId?: string; entityId?: string } = {},
  signal?: AbortSignal,
): Promise<{ items: Contradiction[]; total: number }> {
  return apiFetch(
    `${base(caseId)}/contradictions${query({
      review_status: q.reviewStatus,
      severity: q.severity,
      evidence_id: q.evidenceId,
      entity_id: q.entityId,
    })}`,
    { signal },
  );
}

export function getContradiction(caseId: string, id: string, signal?: AbortSignal) {
  return apiFetch<ContradictionDetail>(`${base(caseId)}/contradictions/${id}`, { signal });
}

export function reviewContradiction(
  caseId: string,
  id: string,
  body: { action: ContradictionAction; note?: string; reviewer?: string; evidence_id?: string },
): Promise<ContradictionDetail> {
  return apiFetch<ContradictionDetail>(
    `${base(caseId)}/contradictions/${id}/review`,
    post(body),
  );
}

export function addAlternative(
  caseId: string,
  id: string,
  body: {
    explanation: string;
    supporting_evidence?: string;
    weakening_evidence?: string;
    missing_information?: string;
    verification_recommendation?: string;
    author?: string;
  },
): Promise<ContradictionDetail> {
  return apiFetch<ContradictionDetail>(
    `${base(caseId)}/contradictions/${id}/alternatives`,
    post(body),
  );
}

// --- review queue, history, graph, dashboard --------------------------------------

export function reviewQueue(caseId: string, signal?: AbortSignal) {
  return apiFetch<ReviewQueue>(`${base(caseId)}/review-queue`, { signal });
}

export function reviewHistory(
  caseId: string,
  q: { targetType?: string; targetId?: string; limit?: number } = {},
  signal?: AbortSignal,
): Promise<{ items: ReviewAction[]; total: number }> {
  return apiFetch(
    `${base(caseId)}/reviews${query({
      target_type: q.targetType,
      target_id: q.targetId,
      limit: q.limit,
    })}`,
    { signal },
  );
}

export function getGraph(
  caseId: string,
  q: {
    includeClaims?: boolean;
    entityType?: string;
    evidenceId?: string;
    contradictionsOnly?: boolean;
    limit?: number;
  } = {},
  signal?: AbortSignal,
): Promise<Graph> {
  return apiFetch<Graph>(
    `${base(caseId)}/graph${query({
      include_claims: q.includeClaims,
      entity_type: q.entityType,
      evidence_id: q.evidenceId,
      contradictions_only: q.contradictionsOnly,
      limit: q.limit,
    })}`,
    { signal },
  );
}

export function getDashboard(caseId: string, signal?: AbortSignal) {
  return apiFetch<Dashboard>(`${base(caseId)}/dashboard`, { signal });
}

export function evidenceAnalysisSummary(caseId: string, evidenceId: string, signal?: AbortSignal) {
  return apiFetch<EvidenceAnalysisSummary>(
    `${base(caseId)}/evidence/${evidenceId}/analysis-summary`,
    { signal },
  );
}

// --- segment corrections ----------------------------------------------------------

export function segmentReviews(
  caseId: string,
  evidenceId: string,
  segmentId: string,
  signal?: AbortSignal,
) {
  return apiFetch<SegmentReviewList>(
    `${base(caseId)}/evidence/${evidenceId}/segments/${segmentId}/reviews`,
    { signal },
  );
}

export function addSegmentReview(
  caseId: string,
  evidenceId: string,
  segmentId: string,
  body: { corrected_text: string; note?: string; reviewer?: string },
): Promise<SegmentReviewList> {
  return apiFetch<SegmentReviewList>(
    `${base(caseId)}/evidence/${evidenceId}/segments/${segmentId}/reviews`,
    post(body),
  );
}

// --- speech models and PDF previews -----------------------------------------------

export function listAudioModels(signal?: AbortSignal) {
  return apiFetch<AudioModelList>(`/api/audio/models`, { signal });
}

/** A rendered PNG of one PDF page, as a Blob (case-scoped endpoint). */
export async function fetchPdfPageImage(
  caseId: string,
  evidenceId: string,
  page: number,
  dpi: number,
  signal?: AbortSignal,
): Promise<Blob> {
  return apiBlob(`${base(caseId)}/evidence/${evidenceId}/pages/${page}/image?dpi=${dpi}`, signal);
}
