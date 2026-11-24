// Pure helpers that decide what an empty or zero-count view may honestly say, based
// on the case's latest analysis run. No React and no imports, so Node can test them.
//
// The rule: never describe a result that no analysis produced. Before any run, a view
// says the case has not been analysed. A zero after a completed run is described as
// "the latest analysis returned none", never as verified, consistent or all clear.

export type AnalysisPhase = "unknown" | "never" | "running" | "completed" | "failed";

export interface RunLike {
  status: string; // "running" | "completed" | "failed" from the backend
}

/**
 * Phase of the case's analysis. `loaded` is false until the latest-run request has
 * succeeded; until then the phase is "unknown" (nothing may be claimed).
 */
export function analysisPhase(run: RunLike | null | undefined, loaded: boolean): AnalysisPhase {
  if (!loaded) return "unknown";
  if (!run) return "never";
  if (run.status === "running") return "running";
  if (run.status === "completed") return "completed";
  if (run.status === "failed") return "failed";
  return "unknown";
}

export type EmptyKind = "claims" | "contradictions" | "review" | "entities" | "graph";

export interface EmptyCopy {
  title: string;
  body: string;
}

const NOUN: Record<EmptyKind, string> = {
  claims: "claims",
  contradictions: "potential inconsistencies",
  review: "items awaiting review",
  entities: "entities",
  graph: "graph connections",
};

/** Text for an empty list. `filtered` = the user narrowed the list with filters. */
export function emptyStateCopy(
  kind: EmptyKind,
  phase: AnalysisPhase,
  options: { filtered?: boolean } = {},
): EmptyCopy {
  const noun = NOUN[kind];
  switch (phase) {
    case "unknown":
      return {
        title: "Analysis status unavailable",
        body: "The status of this case's analysis could not be loaded, so it is not known whether any " +
          `${noun} exist. Reload the page to try again.`,
      };
    case "never":
      return {
        title: "This case has not been analysed yet",
        body:
          `No ${noun} exist because no analysis has been run. Process the evidence, then use ` +
          "Run analysis to extract claims, entities and potential inconsistencies.",
      };
    case "running":
      return {
        title: "Analysis in progress",
        body: `An analysis of this case is running. ${capitalise(noun)} will appear here when it finishes.`,
      };
    case "failed":
      return {
        title: "The latest analysis failed",
        body:
          `It stopped before finishing, so the absence of ${noun} here says nothing about the ` +
          "evidence. Run the analysis again.",
      };
    case "completed":
      if (options.filtered) {
        return {
          title: `No ${noun} match the filters`,
          body: "Clear or change the filters to see the rest.",
        };
      }
      return completedZero(kind);
  }
}

function completedZero(kind: EmptyKind): EmptyCopy {
  switch (kind) {
    case "claims":
      return {
        title: "The latest analysis found no claims",
        body:
          "The rules found no checkable statements (identifiers, times, dates, quantities, " +
          "locations) in the processed evidence. This does not mean the evidence contains none.",
      };
    case "contradictions":
      return {
        title: "The latest analysis found no potential inconsistencies",
        body:
          "Under the current rules, no two claims about the same identifier disagreed. Only times " +
          "and quantities are compared; location conflicts are not checked. This does not mean " +
          "the sources agree or that no real-world inconsistency exists.",
      };
    case "review":
      return {
        title: "The latest analysis left nothing awaiting review",
        body:
          "Every item it produced has a reviewer decision, or it produced none. This does not mean " +
          "the evidence has been verified.",
      };
    case "entities":
      return {
        title: "The latest analysis found no entities",
        body:
          "No identifiers, vehicles, locations or email contacts were found in its claims. Names " +
          "of people and organisations in free text are not extracted, so this does not mean the " +
          "evidence mentions none.",
      };
    case "graph":
      return {
        title: "The latest analysis produced nothing to connect",
        body:
          "It created no claims or entities, so there are no connections to draw. This does not " +
          "mean the evidence items are unrelated.",
      };
  }
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** A count shown in a stat tile. Before a run there is no count to show. */
export function countValue(count: number, phase: AnalysisPhase): string {
  if (phase === "never" || phase === "unknown") return "—";
  return String(count);
}

/** Hint under a review-related stat tile. */
export function countHint(count: number, phase: AnalysisPhase): string {
  switch (phase) {
    case "unknown":
      return "analysis status unavailable";
    case "never":
      return "not analysed yet";
    case "running":
      return "analysis running";
    case "failed":
      return "latest analysis failed";
    case "completed":
      return count === 0 ? "none after the latest analysis" : "awaiting a human decision";
  }
}

/**
 * Tone for review-related counts. Amber when something awaits review; otherwise
 * neutral. Never green: a zero is not an all-clear.
 */
export function countTone(count: number, phase: AnalysisPhase): "amber" | "neutral" | "red" {
  if (phase === "failed") return "red";
  if ((phase === "completed" || phase === "running") && count > 0) return "amber";
  return "neutral";
}

/** Short banner text for a list that has items but whose latest run is not complete. */
export function phaseNotice(phase: AnalysisPhase): string | null {
  switch (phase) {
    case "running":
      return "An analysis is running. This list will refresh when it finishes.";
    case "failed":
      return "The latest analysis failed. The items below come from earlier runs and may be incomplete.";
    case "unknown":
      return "The analysis status could not be loaded.";
    default:
      return null;
  }
}
