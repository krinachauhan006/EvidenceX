// TypeScript types mirroring the backend Pydantic schemas (app/modules/cases/schemas.py).
// Later these can be generated from the FastAPI OpenAPI schema to prevent drift.

export type CaseStatus = "open" | "archived";

export interface Case {
  id: string;
  title: string;
  description: string | null;
  status: CaseStatus;
  created_at: string;
  updated_at: string;
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
