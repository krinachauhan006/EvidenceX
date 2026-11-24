// TypeScript types mirroring backend/app/modules/analysis/schemas.py.
// Keep in sync by hand until types are generated from the OpenAPI schema.

export type ClaimReviewStatus = "unreviewed" | "needs_verification" | "verified" | "rejected";
export type ContradictionStatus =
  | "unreviewed"
  | "confirmed"
  | "rejected"
  | "unresolved"
  | "resolved";
export type ResolutionStatus = "unresolved" | "confirmed" | "merged" | "rejected";
export type AlternativeBasis = "source_supported" | "machine_hypothesis" | "human";
export type Severity = "low" | "medium" | "high";

/** Loose by design: claim locators are segment locators plus optional refinements. */
export type ClaimLocator = Record<string, unknown> & { kind?: string };

export interface EventTime {
  raw?: string;
  kind?: string;
  precision?: string;
  minutes?: number | null;
  range?: [number, number] | null;
  date_known?: boolean;
  date_raw?: string;
  note?: string;
  [key: string]: unknown;
}

export interface AnalysisRun {
  id: string;
  case_id: string;
  status: "running" | "completed" | "failed";
  method: string;
  started_at: string;
  completed_at: string | null;
  error: string | null;
  stats: Record<string, unknown>;
}

export interface Mention {
  entity_id: string;
  entity_type: string;
  display_name: string;
  mention_text: string;
  role: string | null;
}

export interface ClaimBrief {
  id: string;
  evidence_id: string;
  evidence_name: string;
  evidence_type: string;
  segment_id: string | null;
  modality: string;
  quote: string;
  claim_text: string;
  locator: ClaimLocator | null;
  event_time: EventTime | null;
  review_status: ClaimReviewStatus;
  source_current: boolean;
}

export interface Claim {
  id: string;
  case_id: string;
  evidence_id: string;
  evidence_name: string;
  evidence_type: string;
  extraction_id: string;
  run_number: number;
  source_current: boolean;
  segment_id: string | null;
  analysis_run_id: string | null;
  claim_text: string;
  claim_type: string;
  subject: string | null;
  predicate: string | null;
  predicate_key: string | null;
  object_value: string | null;
  event_time: EventTime | null;
  location: string | null;
  quote: string;
  quote_start: number | null;
  quote_end: number | null;
  locator: ClaimLocator | null;
  modality: string;
  grounding: "grounded" | "insufficient";
  extraction_method: string;
  is_inferred: boolean;
  extraction_confidence: number | null;
  source_engine_confidence: number | null;
  uncertainty: string[];
  review_status: ClaimReviewStatus;
  reviewed_text: string | null;
  review_note: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
  entities: Mention[];
  contradiction_count: number;
}

export interface ClaimList {
  items: Claim[];
  total: number;
  limit: number;
  offset: number;
}

export interface ReviewAction {
  id: string;
  target_type: string;
  target_id: string;
  action: string;
  from_status: string | null;
  to_status: string | null;
  note: string | null;
  payload: Record<string, unknown>;
  reviewer: string | null;
  created_at: string;
}

export interface Relationship {
  id: string;
  relation_type: string;
  rationale: string;
  origin: string;
  review_status: ClaimReviewStatus;
  via_entity_id: string | null;
  via_entity_name: string | null;
  source_claim: ClaimBrief;
  target_claim: ClaimBrief;
  created_at: string;
}

export interface SegmentRef {
  id: string;
  extraction_id: string;
  seq: number;
  segment_type: string;
  text: string | null;
  locator: ClaimLocator;
  engine_confidence: number | null;
}

export interface ClaimDetail extends Claim {
  segment: SegmentRef | null;
  relationships: Relationship[];
  contradiction_ids: string[];
  history: ReviewAction[];
}

export interface Entity {
  id: string;
  entity_type: string;
  display_name: string;
  normalized_key: string;
  aliases: string[];
  resolution_status: ResolutionStatus;
  merged_into_id: string | null;
  review_status: string;
  review_note: string | null;
  mention_count: number;
  evidence_count: number;
  created_at: string;
}

export interface Candidate {
  entity_a: Entity;
  entity_b: Entity;
  reason: string;
}

export interface EntityDetail extends Entity {
  mentions: { claim_id: string; mention_text: string; role: string | null; claim: ClaimBrief }[];
  candidates: Candidate[];
  merged_from: Entity[];
  history: ReviewAction[];
}

export interface Explanation {
  first_states: string;
  second_states: string;
  why: string;
  uncertain: string;
  would_resolve: string;
}

export interface Alternative {
  id: string;
  explanation: string;
  supporting_evidence: string | null;
  weakening_evidence: string | null;
  missing_information: string | null;
  verification_recommendation: string | null;
  basis: AlternativeBasis;
  status: string;
  author: string | null;
  created_at: string;
}

export interface Contradiction {
  id: string;
  category: string;
  severity: Severity;
  explanation: Explanation;
  detection_confidence: number;
  uncertainty: string[];
  origin: string;
  review_status: ContradictionStatus;
  reviewer_decision: string | null;
  resolution_note: string | null;
  linked_evidence_ids: string[];
  via_entity_id: string | null;
  via_entity_name: string | null;
  claim_a: ClaimBrief;
  claim_b: ClaimBrief;
  claims_current: boolean;
  alternatives: Alternative[];
  created_at: string;
  updated_at: string;
}

export interface ContradictionDetail extends Contradiction {
  history: ReviewAction[];
}

export interface ReviewQueue {
  claims: Claim[];
  contradictions: Contradiction[];
  candidates: Candidate[];
  counts: Record<string, number>;
}

export type GraphNodeKind = "evidence" | "claim" | "entity" | "contradiction";

export interface GraphNode {
  id: string;
  kind: GraphNodeKind;
  label: string;
  sublabel: string | null;
  status: string | null;
  ref_id: string;
  evidence_id: string | null;
  data: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  kind: string;
  label: string | null;
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
  counts: Record<string, number>;
}

export interface Dashboard {
  evidence: {
    total: number;
    by_type: Record<string, number>;
    by_status: Record<string, number>;
    bytes: number;
  };
  segments: number;
  claims: {
    total: number;
    by_status: Record<string, number>;
    by_type: Record<string, number>;
    by_modality: Record<string, number>;
    insufficient_grounding: number;
  };
  entities: { total: number; by_type: Record<string, number>; candidates: number };
  relationships: number;
  contradictions: {
    total: number;
    by_status: Record<string, number>;
    by_severity: Record<string, number>;
  };
  review_queue: number;
  latest_run: AnalysisRun | null;
  recent_activity: ReviewAction[];
  top_entities: Entity[];
  claim_method: string;
}

export interface EvidenceAnalysisSummary {
  evidence_id: string;
  segments: number;
  claims: number;
  entities: number;
  relationships: number;
  contradictions: number;
  awaiting_review: number;
  analysed: boolean;
}

export interface SegmentReview {
  id: string;
  segment_id: string;
  evidence_id: string;
  corrected_text: string;
  note: string | null;
  reviewer: string | null;
  created_at: string;
}

export interface SegmentReviewList {
  original_text: string | null;
  items: SegmentReview[];
  total: number;
}

export type ClaimAction = "verify" | "reject" | "needs_verification" | "edit" | "note";
export type EntityAction = "confirm" | "reject" | "merge" | "unmerge" | "mark_distinct" | "note";
export type ContradictionAction =
  | "confirm"
  | "reject"
  | "unresolved"
  | "resolve"
  | "note"
  | "link_evidence";
