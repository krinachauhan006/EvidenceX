// TypeScript types mirroring the backend processing schemas
// (app/modules/processing/schemas.py and locators.py). Keep them in sync by hand
// until types are generated from the OpenAPI schema.

import type { EvidenceType, ProcessingStatus } from "@/lib/types/evidence";

export type RunStatus = "completed" | "failed";
export type ExtractionOutcome = "ok" | "partial" | "needs_ocr" | "empty";
export type SkipReason = "already_completed" | "already_processing" | "no_extractor";

// --- locators (discriminated on `kind`) ----------------------------------------

export type BBox = [number, number, number, number];

export interface PdfLocator {
  kind: "pdf";
  page: number; // 1-based
  bbox: BBox | null; // [x0, y0, x1, y1] in PDF points
  page_width: number | null;
  page_height: number | null;
  unit: "pt";
}

export interface ImageLocator {
  kind: "image";
  bbox: BBox; // [x0, y0, x1, y1] in pixels
  width: number;
  height: number;
  unit: "px";
}

export interface AudioLocator {
  kind: "audio";
  start: number; // seconds
  end: number;
}

export interface CsvLocator {
  kind: "csv";
  row: number; // 1-based record number, blank records included
  line: number; // first physical line of the record
  column: string | null; // null = the whole row
}

export interface XlsxLocator {
  kind: "xlsx";
  sheet: string;
  row: number;
  range: string; // for example "A12:F12"
}

export interface EmailLocator {
  kind: "email";
  part: "header" | "body_text" | "body_html" | "attachment";
  name: string | null; // header name or attachment filename
  index: number | null; // 0-based part index
}

export interface VideoLocator {
  kind: "video";
  t: number; // seconds from the start of the video
  frame_width: number;
  frame_height: number;
  bbox: BBox | null; // text region on the frame (OCR line), in frame pixels
  unit: "px";
}

export type Locator =
  | PdfLocator
  | ImageLocator
  | AudioLocator
  | CsvLocator
  | XlsxLocator
  | EmailLocator
  | VideoLocator;

// --- extraction runs -----------------------------------------------------------

export interface ExtractionWarning {
  code: string;
  message: string;
  detail: Record<string, unknown> | null;
}

/** One extraction run. Runs are append-only history; reprocessing adds a run. */
export interface Extraction {
  id: string;
  evidence_id: string;
  case_id: string;
  run_number: number;
  run_status: RunStatus;
  is_current: boolean;
  extractor: string;
  extractor_version: string;
  source_sha256: string;
  outcome: ExtractionOutcome | null; // null for failed runs
  error_code: string | null;
  error_message: string | null;
  doc_metadata: Record<string, unknown>;
  warnings: ExtractionWarning[];
  segment_count: number;
  duration_ms: number;
  started_at: string;
  recorded_at: string; // when the run was recorded (the extraction timestamp)
}

export interface ExtractionList {
  items: Extraction[]; // newest run first
  total: number;
}

export interface Segment {
  id: string;
  extraction_id: string;
  seq: number;
  segment_type: string;
  text: string | null;
  data: Record<string, unknown> | null;
  locator: Locator;
  page: number | null;
  t_start: number | null;
  t_end: number | null;
  engine_confidence: number | null; // engine-reported, 0..1
  language: string | null;
  // Segment text is the original extraction and is never edited. A human correction
  // is stored separately (segment_reviews); the newest one is reported here.
  review_status: "unreviewed" | "reviewed";
  reviewed_text?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
}

export interface AudioModel {
  name: string;
  repo: string;
  available: boolean;
  size_bytes: number | null;
  problem: string | null;
  is_default: boolean;
}

export interface AudioModelList {
  default: string;
  default_available: boolean;
  items: AudioModel[];
}

export interface SegmentList {
  items: Segment[];
  total: number;
  limit: number;
  offset: number;
}

export interface SegmentQuery {
  extractionId?: string; // defaults to the current run on the server
  page?: number;
  segmentType?: string;
  limit?: number;
  offset?: number;
}

// --- processing requests and status --------------------------------------------

export interface SkippedItem {
  evidence_id: string;
  reason: SkipReason;
}

export interface ProcessAccepted {
  queued: string[];
  skipped: SkippedItem[];
}

export interface ProcessingStatusInfo {
  evidence_id: string;
  status: ProcessingStatus;
  error: string | null;
  error_code: string | null;
  attempts: number;
  started_at: string | null;
  completed_at: string | null;
  // True when an earlier successful run is still available even if the latest
  // attempt failed.
  has_current_extraction: boolean;
  current_extraction: Extraction | null;
}

export interface ProcessingItem {
  evidence_id: string;
  original_filename: string;
  evidence_type: EvidenceType;
  status: ProcessingStatus;
  error_code: string | null;
  attempts: number;
  outcome: ExtractionOutcome | null;
  segment_count: number;
  run_number: number | null; // run number of the current run, if any
  extractor_available: boolean;
}

export interface StatusCounts {
  total: number;
  pending: number;
  processing: number;
  completed: number;
  failed: number;
}

export interface CaseProcessingSummary {
  counts: StatusCounts;
  items: ProcessingItem[];
}
