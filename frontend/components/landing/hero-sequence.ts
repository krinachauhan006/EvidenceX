// Timeline of the landing-page hero illustration (fictional "Missing shipment" case).
// Pure data + helpers so the order and the reduced-motion behaviour are unit-tested.

export type HeroPhase =
  | "sources" // evidence cards present
  | "illuminate" // source documents light up in turn
  | "claims" // extracted claims appear
  | "trace" // lines draw from each source to its claim
  | "converge" // claims connect to the suggested event
  | "event" // event node pulses once it has accounts
  | "inconsistency" // amber: possible inconsistency between two accounts
  | "alternatives" // benign alternative explanations
  | "review"; // settled: awaiting human review

export const HERO_STEPS: readonly { phase: HeroPhase; at: number; label: string }[] = [
  { phase: "sources", at: 0, label: "Six evidence files in one case" },
  { phase: "illuminate", at: 500, label: "Each file is read in its own format" },
  { phase: "claims", at: 1700, label: "Statements are extracted as claims" },
  { phase: "trace", at: 2500, label: "Every claim is traced to its exact source" },
  { phase: "converge", at: 3600, label: "Related claims suggest one event" },
  { phase: "event", at: 4500, label: "Suggested event: arrival on 12 Oct" },
  { phase: "inconsistency", at: 5400, label: "Two accounts may not agree" },
  { phase: "alternatives", at: 6400, label: "Benign explanations are listed" },
  { phase: "review", at: 7400, label: "Awaiting human review" },
];

export const FINAL_STEP = HERO_STEPS.length - 1;

/** Index of the step showing after `elapsed` ms of (unpaused) playback. */
export function stepAt(elapsed: number): number {
  let i = 0;
  for (let k = 0; k < HERO_STEPS.length; k++) if (elapsed >= HERO_STEPS[k].at) i = k;
  return i;
}

/** Ms until the next step after `elapsed`, or null once settled. */
export function msToNext(elapsed: number): number | null {
  const next = HERO_STEPS[stepAt(elapsed) + 1];
  return next ? Math.max(0, next.at - elapsed) : null;
}

/** Whether something introduced at `phase` is visible while `step` is showing. */
export function shown(phase: HeroPhase, step: number): boolean {
  return HERO_STEPS.findIndex((s) => s.phase === phase) <= step;
}

/** Without motion the illustration starts (and stays) at its complete final state. */
export function initialStep(reducedMotion: boolean): number {
  return reducedMotion ? FINAL_STEP : 0;
}
