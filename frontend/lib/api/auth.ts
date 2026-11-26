// Sign-in, registration and case membership (backend/app/modules/auth/router.py).
// The session lives in an HttpOnly cookie set by the API; nothing is stored here.

import { apiFetch } from "@/lib/api/client";
import type { Case, Role } from "@/lib/types/case";
import type { MemberList, Session, User } from "@/lib/types/phase2";

const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export function register(body: {
  email: string;
  display_name: string;
  password: string;
}): Promise<Session> {
  return apiFetch<Session>("/api/auth/register", { ...post(body), allowAnonymous: true });
}

export function login(body: { email: string; password: string }): Promise<Session> {
  return apiFetch<Session>("/api/auth/login", { ...post(body), allowAnonymous: true });
}

export function logout(): Promise<null> {
  return apiFetch<null>("/api/auth/logout", { method: "POST", allowAnonymous: true });
}

/** The signed-in user, or an ApiError(401) when there is no valid session. */
export function me(signal?: AbortSignal): Promise<User> {
  return apiFetch<User>("/api/auth/me", { signal, allowAnonymous: true });
}

export function listMembers(caseId: string, signal?: AbortSignal): Promise<MemberList> {
  return apiFetch<MemberList>(`/api/cases/${caseId}/members`, { signal });
}

export function addMember(caseId: string, email: string, role: Role): Promise<MemberList> {
  return apiFetch<MemberList>(`/api/cases/${caseId}/members`, post({ email, role }));
}

export function changeMemberRole(caseId: string, userId: string, role: Role): Promise<MemberList> {
  return apiFetch<MemberList>(`/api/cases/${caseId}/members/${userId}`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

export function removeMember(caseId: string, userId: string): Promise<MemberList> {
  return apiFetch<MemberList>(`/api/cases/${caseId}/members/${userId}`, { method: "DELETE" });
}

export function setAiConsent(caseId: string, allowed: boolean): Promise<Case> {
  return apiFetch<Case>(`/api/cases/${caseId}/consent`, post({ ai_processing_allowed: allowed }));
}

export { safeNext } from "@/lib/safe-next";
