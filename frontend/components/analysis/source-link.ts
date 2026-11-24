// Pure helpers for navigating from a claim to its exact source location in the
// evidence workspace. No React and no runtime imports, so Node can test them.

export type WorkspaceTab =
  | "overview"
  | "preview"
  | "content"
  | "claims"
  | "entities"
  | "relationships"
  | "processing"
  | "runs";

export const WORKSPACE_TABS: { id: WorkspaceTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "preview", label: "Original preview" },
  { id: "content", label: "Extracted content" },
  { id: "claims", label: "Claims" },
  { id: "entities", label: "Entities" },
  { id: "relationships", label: "Relationships" },
  { id: "processing", label: "Processing details" },
  { id: "runs", label: "Run history" },
];

export interface SourceTarget {
  evidenceId: string;
  segmentId: string | null;
  claimId?: string | null;
  locator?: Record<string, unknown> | null;
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Link to the evidence workspace, opened on the original preview at the source. */
export function sourceHref(caseId: string, target: SourceTarget): string {
  const params = new URLSearchParams({ tab: "preview" });
  if (target.segmentId) params.set("segment", target.segmentId);
  if (target.claimId) params.set("claim", target.claimId);
  const loc = target.locator ?? null;
  if (loc) {
    if (finite(loc.page)) params.set("page", String(loc.page));
    const t = finite(loc.word_start) ? loc.word_start : loc.start;
    if (loc.kind === "audio" && finite(t)) params.set("t", String(Math.round(t * 10) / 10));
  }
  return `/cases/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(
    target.evidenceId,
  )}?${params.toString()}`;
}

export interface ParsedFocus {
  tab: WorkspaceTab;
  segmentId: string | null;
  claimId: string | null;
  page: number | null;
  t: number | null;
}

const TAB_IDS = new Set<string>(WORKSPACE_TABS.map((t) => t.id));
const ID = /^[0-9a-fA-F-]{8,64}$/;

/** Read workspace focus from URL search params. Invalid values are ignored. */
export function parseFocus(get: (key: string) => string | null): ParsedFocus {
  const tab = get("tab");
  const segment = get("segment");
  const claim = get("claim");
  const page = Number(get("page"));
  const t = Number(get("t"));
  return {
    tab: tab && TAB_IDS.has(tab) ? (tab as WorkspaceTab) : "overview",
    segmentId: segment && ID.test(segment) ? segment : null,
    claimId: claim && ID.test(claim) ? claim : null,
    page: Number.isInteger(page) && page >= 1 ? page : null,
    t: get("t") !== null && Number.isFinite(t) && t >= 0 ? t : null,
  };
}

/** Bounding box as CSS percentages of the page/image, or null when unusable. */
export function bboxPercent(
  bbox: unknown,
  width: unknown,
  height: unknown,
): { left: number; top: number; width: number; height: number } | null {
  if (!Array.isArray(bbox) || bbox.length !== 4 || !bbox.every(finite)) return null;
  if (!finite(width) || !finite(height) || width <= 0 || height <= 0) return null;
  const [x0, y0, x1, y1] = bbox as number[];
  if (x1 < x0 || y1 < y0) return null;
  const clamp = (v: number) => Math.min(100, Math.max(0, v));
  return {
    left: clamp((x0 / width) * 100),
    top: clamp((y0 / height) * 100),
    width: clamp(((x1 - x0) / width) * 100),
    height: clamp(((y1 - y0) / height) * 100),
  };
}
