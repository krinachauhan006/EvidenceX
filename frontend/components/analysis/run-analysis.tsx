"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { latestAnalysis, startAnalysis } from "@/lib/api/analysis";
import type { AnalysisRun } from "@/lib/types/analysis";
import { formatDateTime } from "@/lib/format";
import { methodLabel } from "@/components/analysis/review-labels";
import { BUTTON_PRIMARY } from "@/components/ui/primitives";
import { errorText } from "@/hooks/use-api";

const POLL_MS = 1500;

interface Props {
  caseId: string;
  /** Called after a run settles (completed or failed). */
  onDone?: () => void;
  /**
   * Called whenever the latest run is known: on first load, when a run starts, while
   * it is polled and when it settles. `null` means the case has never been analysed.
   */
  onRun?: (run: AnalysisRun | null) => void;
}

/**
 * Starts a case analysis (claims, entities, relationships, potential
 * inconsistencies) and polls until it settles.
 */
export function RunAnalysis({ caseId, onDone, onRun }: Props) {
  const [run, setRun] = useState<AnalysisRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onDoneRef = useRef(onDone);
  const onRunRef = useRef(onRun);
  onDoneRef.current = onDone;
  onRunRef.current = onRun;

  const publish = useCallback((value: AnalysisRun | null) => {
    setRun(value);
    onRunRef.current?.(value);
  }, []);

  const poll = useCallback(async () => {
    try {
      const { run: latest } = await latestAnalysis(caseId);
      publish(latest);
      if (latest?.status === "running") {
        timer.current = setTimeout(() => void poll(), POLL_MS);
      } else if (latest) {
        onDoneRef.current?.();
      }
    } catch (err) {
      setError(errorText(err, "Could not read the analysis status."));
    }
  }, [caseId, publish]);

  useEffect(() => {
    void (async () => {
      try {
        const { run: latest } = await latestAnalysis(caseId);
        publish(latest);
        if (latest?.status === "running") timer.current = setTimeout(() => void poll(), POLL_MS);
      } catch {
        // Status stays unknown for the pages; the button still works.
      }
    })();
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [caseId, poll, publish]);

  async function start() {
    setError(null);
    try {
      publish(await startAnalysis(caseId));
      timer.current = setTimeout(() => void poll(), 400);
    } catch (err) {
      setError(errorText(err, "The analysis could not be started."));
    }
  }

  const running = run?.status === "running";
  const errors = Array.isArray(run?.stats?.errors) ? (run?.stats.errors as unknown[]).length : 0;
  return (
    <div className="flex flex-col items-start gap-1 lg:items-end">
      <button type="button" onClick={() => void start()} disabled={running} className={BUTTON_PRIMARY}>
        {running ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
        ) : (
          <Sparkles className="h-3.5 w-3.5" aria-hidden />
        )}
        {running ? "Analysing…" : "Run analysis"}
      </button>
      {run && !running && (
        <span className="max-w-md text-xs text-slate-500 lg:text-right">
          Last run {formatDateTime(run.completed_at ?? run.started_at)} · {methodLabel(run.method)}
          {run.status === "failed" && <span className="text-failed"> · failed</span>}
          {errors > 0 && (
            <span className="text-failed">
              {" "}
              · {errors} item{errors === 1 ? "" : "s"} could not be analysed
            </span>
          )}
        </span>
      )}
      {error && (
        <span role="alert" className="max-w-md text-xs text-failed lg:text-right">
          {error}
        </span>
      )}
    </div>
  );
}
