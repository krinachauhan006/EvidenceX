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
  // True when the server leaves this file type to the external processing worker.
  // Optional so an older backend (without the field) is treated as "no".
  external_worker?: boolean;
  // True when an editor's browser may run the OCR / speech engine for this item.
  browser_processing?: boolean;
}

export interface EvidenceList {
  items: Evidence[];
  total: number;
}
