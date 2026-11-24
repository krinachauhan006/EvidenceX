import { apiFetch } from "@/lib/api/client";
import type {
  Case,
  CaseCreate,
  CaseList,
  CaseStatus,
  CaseUpdate,
} from "@/lib/types/case";

export function listCases(params?: {
  status?: CaseStatus;
  limit?: number;
  offset?: number;
}): Promise<CaseList> {
  const search = new URLSearchParams();
  if (params?.status) search.set("status", params.status);
  if (params?.limit != null) search.set("limit", String(params.limit));
  if (params?.offset != null) search.set("offset", String(params.offset));
  const qs = search.toString();
  return apiFetch<CaseList>(`/api/cases${qs ? `?${qs}` : ""}`);
}

export function getCase(id: string): Promise<Case> {
  return apiFetch<Case>(`/api/cases/${id}`);
}

export function createCase(data: CaseCreate): Promise<Case> {
  return apiFetch<Case>("/api/cases", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateCase(id: string, data: CaseUpdate): Promise<Case> {
  return apiFetch<Case>(`/api/cases/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function archiveCase(id: string): Promise<Case> {
  return apiFetch<Case>(`/api/cases/${id}/archive`, { method: "POST" });
}

export function deleteCase(id: string): Promise<null> {
  return apiFetch<null>(`/api/cases/${id}`, { method: "DELETE" });
}
