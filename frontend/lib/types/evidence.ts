// TypeScript types mirroring the backend evidence schemas
// (app/modules/evidence/schemas.py).

export type EvidenceType = "document" | "image" | "audio" | "tabular" | "email" | "video";
export type ProcessingStatus = "pending" | "processing" | "completed" | "failed";

export interface Evidence {
  id: string;
  case_id: string;
  original_filename: string;
  evidence_type: EvidenceType;
  mime_type: string;
  byte_size: number;
  sha256: string;
  processing_status: ProcessingStatus;
  processing_error: string | null;
  processing_error_code: string | null;
  processing_started_at: string | null;
  processing_completed_at: string | null;
  processing_attempts: number;
  uploaded_at: string;
}

export interface EvidenceList {
  items: Evidence[];
  total: number;
}
