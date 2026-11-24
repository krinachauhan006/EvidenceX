// Pure labels, tones and allowed actions for review states. The transitions mirror
// backend/app/modules/analysis/service.py; the server is the authority and answers
// 409 for anything else.

export type Tone = "neutral" | "amber" | "green" | "red" | "blue";

const CLAIM_STATUS: Record<string, { label: string; tone: Tone }> = {
  unreviewed: { label: "Unreviewed", tone: "neutral" },
  needs_verification: { label: "Needs verification", tone: "amber" },
  verified: { label: "Verified by reviewer", tone: "green" },
  rejected: { label: "Rejected by reviewer", tone: "red" },
};

const CONTRADICTION_STATUS: Record<string, { label: string; tone: Tone }> = {
  unreviewed: { label: "Awaiting review", tone: "amber" },
  unresolved: { label: "Unresolved", tone: "amber" },
  confirmed: { label: "Inconsistency confirmed", tone: "amber" },
  rejected: { label: "Not an inconsistency", tone: "neutral" },
  resolved: { label: "Resolved", tone: "green" },
};

export function claimStatus(status: string): { label: string; tone: Tone } {
  return CLAIM_STATUS[status] ?? { label: status, tone: "neutral" };
}

export function contradictionStatus(status: string): { label: string; tone: Tone } {
  return CONTRADICTION_STATUS[status] ?? { label: status, tone: "neutral" };
}

const CLAIM_NEXT: Record<string, ("verify" | "reject" | "needs_verification")[]> = {
  unreviewed: ["verify", "needs_verification", "reject"],
  needs_verification: ["verify", "reject"],
  verified: ["needs_verification"],
  rejected: ["needs_verification"],
};

export function claimActions(status: string): ("verify" | "reject" | "needs_verification")[] {
  return CLAIM_NEXT[status] ?? [];
}

const CONTRADICTION_NEXT: Record<string, ("confirm" | "reject" | "unresolved" | "resolve")[]> = {
  unreviewed: ["confirm", "unresolved", "reject"],
  unresolved: ["confirm", "resolve", "reject"],
  confirmed: ["resolve", "unresolved"],
  rejected: ["unresolved"],
  resolved: ["unresolved"],
};

export function contradictionActions(
  status: string,
): ("confirm" | "reject" | "unresolved" | "resolve")[] {
  return CONTRADICTION_NEXT[status] ?? [];
}

export const ACTION_LABELS: Record<string, string> = {
  verify: "Verify",
  reject: "Reject",
  needs_verification: "Needs verification",
  edit: "Edit interpretation",
  note: "Note",
  confirm: "Confirm inconsistency",
  unresolved: "Mark unresolved",
  resolve: "Resolve",
  link_evidence: "Link evidence",
  add_alternative: "Alternative added",
  merge: "Merge",
  unmerge: "Unmerge",
  mark_distinct: "Mark distinct",
  correct_text: "Transcript corrected",
};

export function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action.replace(/_/g, " ");
}

function hhmm(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

/** How a time was recorded, without adding precision that is not there. */
export function eventTimeLabel(t: Record<string, unknown> | null | undefined): string | null {
  if (!t || typeof t.raw !== "string") return null;
  const raw = t.raw;
  const precision = typeof t.precision === "string" ? t.precision : "unknown";
  if (precision === "unknown") return `"${raw}" (ambiguous; not interpreted)`;
  const range = t.range;
  if (
    precision === "range" &&
    Array.isArray(range) &&
    range.length === 2 &&
    range.every((v) => typeof v === "number")
  ) {
    return `"${raw}" (approximate: ${hhmm(range[0] as number)}–${hhmm(range[1] as number)})`;
  }
  return `"${raw}" (${precision})`;
}

/** 0.62 -> "62%"; null stays explicit. */
export function percent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "not reported";
  return `${Math.round(value * 100)}%`;
}

export function methodLabel(method: string): string {
  if (method.startsWith("rule_based")) return "Rule-based extraction (not AI)";
  if (method.startsWith("gemini")) return "AI-assisted extraction (Gemini)";
  return method;
}
