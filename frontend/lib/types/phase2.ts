// TypeScript types mirroring backend/app/modules/analysis/schemas_phase2.py and the
// auth/membership schemas (backend/app/modules/auth/schemas.py).

import type { ClaimBrief, ClaimLocator, ReviewAction } from "@/lib/types/analysis";
import type { Role } from "@/lib/types/case";

// --- auth -------------------------------------------------------------------------

export interface User {
  id: string;
  email: string;
  display_name: string;
  created_at: string;
}

export interface Session {
  user: User;
  expires_at: string;
  claimed_cases: number;
}

export interface Member {
  user_id: string;
  email: string;
  display_name: string;
  role: Role;
  added_at: string;
}

export interface MemberList {
  items: Member[];
  my_role: Role;
}

// --- events and timeline ------------------------------------------------------------

export type EventStatus = "proposed" | "confirmed" | "rejected";

export interface EventMember {
  claim: ClaimBrief;
  account_label: string;
  attribution: string | null;
  match_reasons: string[];
  added_by: string;
  date: string | null;
  date_precision: string;
  date_source: string | null;
}

export type ComparisonClass =
  | "same_account"
  | "missing_time"
  | "different_day"
  | "approximate_overlap"
  | "within_tolerance"
  | "possible_rounding"
  | "possible_timezone"
  | "conflict_candidate";

export interface Comparison {
  claim_a_id: string;
  claim_b_id: string;
  account_a: string;
  account_b: string;
  classification: ComparisonClass | string;
  gap_minutes: number | null;
  explanation: string;
  is_candidate: boolean;
}

export interface EventFactor {
  factor: string;
  effect: number;
  detail: string;
}

export interface InvestigationEvent {
  id: string;
  event_type: string;
  title: string;
  anchor_kind: string;
  anchor_key: string;
  event_date: string | null;
  date_precision: string;
  link_basis: string;
  /** Heuristic association score of the rules; not a probability the event happened. */
  association_confidence: number;
  factors: EventFactor[];
  missing_links: string[];
  origin: string;
  status: EventStatus;
  review_note: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
  members: EventMember[];
  comparisons: Comparison[];
  contradiction_ids: string[];
}

export interface EventDetail extends InvestigationEvent {
  history: ReviewAction[];
}

export type EventAction =
  | "confirm"
  | "reject"
  | "reopen"
  | "note"
  | "add_claim"
  | "remove_claim"
  | "split";

export interface TimelineItem {
  claim: ClaimBrief;
  date: string | null;
  date_precision: string;
  date_source: string | null;
  time_raw: string | null;
  time_precision: string | null;
  start_minute: number | null;
  end_minute: number | null;
  tz: string | null;
  events: { id: string; title: string; status: EventStatus }[];
  contradiction_ids: string[];
}

export interface Timeline {
  groups: { date: string | null; items: TimelineItem[] }[];
  total: number;
  undated_note: string;
}

// --- search and questions -------------------------------------------------------------

export interface SearchHit {
  kind: "segment" | "claim" | "entity" | "event";
  id: string;
  evidence_id: string | null;
  evidence_name: string | null;
  segment_id: string | null;
  claim_id: string | null;
  title: string;
  excerpt: string;
  locator: ClaimLocator | null;
  score: number;
  matched: string[];
  why: string;
  review_status: string | null;
  modality: string | null;
}

export interface SearchResult {
  query: string;
  expanded_terms: string[];
  method: string;
  items: SearchHit[];
  total: number;
}

export interface AskCitation {
  ref: string;
  kind: string;
  id: string;
  evidence_name: string | null;
  locator: ClaimLocator | null;
  excerpt: string;
}

export interface AskStatement {
  text: string;
  citations: string[];
  support: "supported" | "interpretation" | "unknown";
}

export interface AskResult {
  question: string;
  method: string;
  answer: AskStatement[];
  citations: AskCitation[];
  removed_unsupported: number;
  notice: string;
}

export interface AiStatus {
  mode: string;
  provider: string | null;
  model: string;
  key_configured: boolean;
  available: boolean;
  consent_required: boolean;
  data_sent: string;
  purposes: string[];
}

// --- reports, exports, audit ----------------------------------------------------------

export interface Report {
  id: string;
  kind: "investigation" | "graph" | string;
  format: string;
  title: string;
  version: number;
  content_sha256: string;
  byte_size: number;
  page_count: number;
  created_by: string | null;
  created_at: string;
  summary: Record<string, unknown>;
}

export interface AuditVerification {
  intact: boolean;
  checked: number;
  broken_at: string | null;
  reason: string | null;
  legacy_unchained: number;
  total: number;
  head?: string | null;
}

export interface WorkspaceSummary {
  cases: { total: number; open: number; archived: number };
  evidence: {
    total: number;
    by_status: Record<string, number>;
    by_type: Record<string, number>;
  };
  review: { open_claims: number; open_contradictions: number; proposed_events: number };
  recent_cases: { id: string; title: string; status: string; updated_at: string }[];
  processing_activity: {
    case_id: string;
    case_title: string | null;
    file: string;
    status: string;
  }[];
}

export interface OcrLanguages {
  engine_available: boolean;
  default: string;
  installed: { code: string; name: string; usable_for_text: boolean }[];
  orientation_detection: boolean;
  install_help: string;
}
