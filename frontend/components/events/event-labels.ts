// Labels for event reconstruction. Pure (no React), so Node can test them.

import type { Tone } from "@/components/analysis/review-labels";

export const COMPARISON_LABEL: Record<string, { label: string; tone: Tone; help: string }> = {
  conflict_candidate: {
    label: "Times appear to conflict",
    tone: "amber",
    help: "The stated times are further apart than the tolerance. This is a possible inconsistency for review, not a finding of fact.",
  },
  possible_timezone: {
    label: "Possible time-zone difference",
    tone: "amber",
    help: "The times differ by about a whole number of hours and no time zone is stated.",
  },
  possible_rounding: {
    label: "Possible rounding",
    tone: "neutral",
    help: "A small difference where at least one account is approximate.",
  },
  within_tolerance: {
    label: "Within tolerance",
    tone: "green",
    help: "Independently recorded times this close are treated as agreeing.",
  },
  approximate_overlap: {
    label: "Approximate times overlap",
    tone: "green",
    help: "At least one time is a range, and the ranges overlap.",
  },
  missing_time: {
    label: "Time missing",
    tone: "neutral",
    help: "One account gives no comparable time. This is missing information, not a disagreement.",
  },
  different_day: {
    label: "Different days",
    tone: "neutral",
    help: "The accounts state different dates; times of day are not compared across days.",
  },
  same_account: {
    label: "Same account",
    tone: "neutral",
    help: "Both statements come from one account, so they are not independent.",
  },
};

export function comparisonLabel(c: string) {
  return COMPARISON_LABEL[c] ?? { label: c.replace(/_/g, " "), tone: "neutral" as Tone, help: "" };
}

export const ANCHOR_LABEL: Record<string, string> = {
  identifier: "Shared identifier",
  vehicle: "Shared vehicle plate",
  location: "Shared named place",
  object: "Same object word only",
};

export function eventStatusTone(status: string): Tone {
  return status === "confirmed" ? "green" : status === "rejected" ? "red" : "blue";
}

/** "10:30" for minutes after midnight. */
export function hhmm(minutes: number): string {
  const m = ((Math.round(minutes) % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

/** Interval in minutes after midnight from a claim's event_time, or null. */
export function claimInterval(t: unknown): [number, number] | null {
  if (!t || typeof t !== "object") return null;
  const v = t as { minutes?: unknown; range?: unknown };
  if (Array.isArray(v.range) && v.range.length === 2 && v.range.every((n) => typeof n === "number")) {
    return [v.range[0] as number, v.range[1] as number];
  }
  if (typeof v.minutes === "number") return [v.minutes, v.minutes];
  return null;
}

/** Axis bounds (minutes) padded around the given intervals, at least one hour wide. */
export function axisBounds(intervals: [number, number][]): [number, number] {
  if (intervals.length === 0) return [0, 1440];
  let lo = Math.min(...intervals.map((i) => i[0]));
  let hi = Math.max(...intervals.map((i) => i[1]));
  const pad = Math.max(15, (hi - lo) * 0.15);
  lo = Math.max(0, lo - pad);
  hi = Math.min(1440, hi + pad);
  if (hi - lo < 60) {
    const mid = (hi + lo) / 2;
    lo = Math.max(0, mid - 30);
    hi = Math.min(1440, mid + 30);
  }
  return [lo, hi];
}
