import { API_BASE, ApiError, apiFetch, apiUpload } from "@/lib/api/client";
import type { Evidence, EvidenceList } from "@/lib/types/evidence";

export function listEvidence(caseId: string): Promise<EvidenceList> {
  return apiFetch<EvidenceList>(`/api/cases/${caseId}/evidence`);
}

export function getEvidence(caseId: string, evidenceId: string): Promise<Evidence> {
  return apiFetch<Evidence>(`/api/cases/${caseId}/evidence/${evidenceId}`);
}

export function uploadEvidence(
  caseId: string,
  file: File,
  onProgress?: (fraction: number) => void,
): Promise<Evidence> {
  const form = new FormData();
  form.append("file", file);
  return apiUpload<Evidence>(`/api/cases/${caseId}/evidence`, form, onProgress);
}

export function deleteEvidence(caseId: string, evidenceId: string): Promise<null> {
  return apiFetch<null>(`/api/cases/${caseId}/evidence/${evidenceId}`, {
    method: "DELETE",
  });
}

/** Absolute URL to stream/download an evidence file. */
export function evidenceDownloadUrl(caseId: string, evidenceId: string): string {
  return `${API_BASE}/api/cases/${caseId}/evidence/${evidenceId}/download`;
}

/**
 * The original uploaded file as a Blob, for in-page audio playback.
 *
 * Uses the same case-scoped download endpoint (no storage path is ever exposed).
 * Loading the whole file lets the player seek reliably to a segment start; uploads
 * are capped at 25 MB. Throws ApiError(404) when the stored file is missing.
 */
export async function fetchEvidenceBlob(
  caseId: string,
  evidenceId: string,
  signal?: AbortSignal,
): Promise<Blob> {
  const res = await fetch(evidenceDownloadUrl(caseId, evidenceId), {
    cache: "no-store",
    signal,
  });
  if (!res.ok) throw new ApiError(res.status, `Request failed (${res.status})`);
  return res.blob();
}

// Supported upload formats, mirrored from the backend validation registry
// (backend/app/modules/evidence/validation.py). Used for the file picker "accept"
// attribute and user-facing guidance. Keep this list identical to what the backend
// accepts: an extension listed here that the server rejects only produces errors.
export const ACCEPTED_EXTENSIONS = [
  ".pdf",
  ".png",
  ".jpg",
  ".jpeg",
  ".webp",
  ".wav",
  ".mp3",
  ".m4a",
  ".csv",
  ".xlsx",
  ".eml",
] as const;

/** "PDF, PNG, JPG, ..." for the upload guidance line. */
export const ACCEPTED_LABEL = ACCEPTED_EXTENSIONS.map((e) => e.slice(1).toUpperCase()).join(
  ", ",
);
