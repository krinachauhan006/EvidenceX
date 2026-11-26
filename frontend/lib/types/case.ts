// TypeScript types mirroring the backend Pydantic schemas (app/modules/cases/schemas.py).
// Later these can be generated from the FastAPI OpenAPI schema to prevent drift.

export type CaseStatus = "open" | "archived";

export interface Case {
  id: string;
  title: string;
  description: string | null;
  status: CaseStatus;
  /** The case owner allowed AI processing of this case's extracted text. */
  ai_processing_allowed: boolean;
  created_at: string;
  updated_at: string;
  /** The signed-in user's role on this case. */
  my_role: Role | null;
}

export type Role = "viewer" | "reviewer" | "editor" | "owner";

const RANK: Record<Role, number> = { viewer: 0, reviewer: 1, editor: 2, owner: 3 };

/** True when ``role`` is at least ``needed`` (the API enforces the same order). */
export function hasRole(role: Role | null | undefined, needed: Role): boolean {
  return role != null && RANK[role] >= RANK[needed];
}

export interface CaseList {
  items: Case[];
  total: number;
  limit: number;
  offset: number;
}

export interface CaseCreate {
  title: string;
  description?: string | null;
}

export interface CaseUpdate {
  title?: string | null;
  description?: string | null;
  status?: CaseStatus | null;
}
