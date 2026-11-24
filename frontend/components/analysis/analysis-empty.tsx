"use client";

import { Loader2 } from "lucide-react";
import { useCaseContext } from "@/components/cases/case-shell";
import {
  emptyStateCopy,
  phaseNotice,
  type EmptyKind,
} from "@/components/analysis/analysis-state";
import { EmptyState } from "@/components/ui/primitives";
import { formatDateTime } from "@/lib/format";

/** Empty list that states what the case's analysis has (and has not) established. */
export function AnalysisEmptyState({ kind, filtered = false }: { kind: EmptyKind; filtered?: boolean }) {
  const { analysisPhase, analysisRun } = useCaseContext();
  const copy = emptyStateCopy(kind, analysisPhase, { filtered });
  return (
    <div data-testid="analysis-empty" data-phase={analysisPhase}>
      <EmptyState title={copy.title}>
        <p>{copy.body}</p>
        {analysisPhase === "completed" && analysisRun?.completed_at && !filtered && (
          <p className="mt-1 text-xs text-slate-600">
            Latest analysis completed {formatDateTime(analysisRun.completed_at)}.
          </p>
        )}
        {analysisPhase === "failed" && analysisRun?.error && (
          <p className="mt-1 text-xs text-failed">{analysisRun.error}</p>
        )}
      </EmptyState>
    </div>
  );
}

/** One-line notice for a populated list whose latest run is running, failed or unknown. */
export function AnalysisPhaseNotice() {
  const { analysisPhase } = useCaseContext();
  const text = phaseNotice(analysisPhase);
  if (!text) return null;
  return (
    <p
      role="status"
      className={
        analysisPhase === "failed"
          ? "mb-3 rounded-md border border-failed/30 bg-failed/10 px-3 py-2 text-xs text-failed"
          : "mb-3 flex items-center gap-2 rounded-md border border-navy-700 bg-navy-800/60 px-3 py-2 text-xs text-slate-300"
      }
    >
      {analysisPhase === "running" && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
      {text}
    </p>
  );
}
