import type { Claim } from "@/lib/types/analysis";
import type { Segment } from "@/lib/types/processing";

/** Props shared by every original-evidence viewer in the workspace. */
export interface ViewerProps {
  caseId: string;
  evidenceId: string;
  segments: Segment[];
  claims: Claim[];
  /** Segment to bring into view and highlight (from a claim or a URL). */
  focusSegmentId: string | null;
  /** Seconds to seek to for audio focus (word-level when available). */
  focusTime?: number | null;
  focusPage?: number | null;
  onFocusSegment: (segmentId: string | null) => void;
  metadata: Record<string, unknown>;
  onSegmentsChanged?: () => void;
}

/** Claims anchored to each segment id. */
export function claimsBySegment(claims: Claim[]): Map<string, Claim[]> {
  const out = new Map<string, Claim[]>();
  for (const c of claims) {
    if (!c.segment_id) continue;
    const list = out.get(c.segment_id) ?? [];
    list.push(c);
    out.set(c.segment_id, list);
  }
  return out;
}
