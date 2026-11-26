import { Loader2, Play, RefreshCw } from "lucide-react";
import type { StatusCounts } from "@/lib/types/processing";

interface Props {
  counts: StatusCounts | null;
  /** Pending items that have an extractor and are not already queued. */
  processableCount: number;
  /** A process-all request is in flight. */
  submitting: boolean;
  /** Status is being polled because work is active. */
  polling: boolean;
  /** Set when status could not be loaded or live updates stopped. */
  error: string | null;
  onProcessAll: () => void;
  onRefresh: () => void;
}

function pct(part: number, total: number): string {
  return total > 0 ? `${(part / total) * 100}%` : "0%";
}

export function ProcessingToolbar({
  counts,
  processableCount,
  submitting,
  polling,
  error,
  onProcessAll,
  onRefresh,
}: Props) {
  if (!counts && !error) return null;

  const total = counts?.total ?? 0;
  const unprocessable = counts ? Math.max(0, counts.pending - processableCount) : 0;

  return (
    <div className="mt-6 rounded-lg border border-navy-800 bg-navy-900 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-medium text-slate-200">
            Processing
            {polling && (
              <span className="inline-flex items-center gap-1 text-xs font-normal text-slate-500">
                <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                updating
              </span>
            )}
          </p>
          {counts && total > 0 && (
            <p className="mt-0.5 text-xs text-slate-500">
              <span className="text-processed">{counts.completed} completed</span>
              {" · "}
              {counts.processing} processing
              {" · "}
              {counts.pending} pending
              {" · "}
              <span className={counts.failed > 0 ? "text-failed" : undefined}>
                {counts.failed} failed
              </span>
            </p>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={onRefresh}
            title="Refresh processing status"
            aria-label="Refresh processing status"
            className="rounded-md border border-navy-700 p-1.5 text-slate-300 hover:bg-navy-800"
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden />
          </button>
          <button
            type="button"
            onClick={onProcessAll}
            disabled={processableCount === 0 || submitting}
            className="inline-flex items-center gap-2 rounded-md bg-navy-700 px-3 py-1.5 text-sm font-medium text-slate-100 hover:bg-navy-600 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Play className="h-4 w-4" aria-hidden />
            )}
            Process all pending ({processableCount})
          </button>
        </div>
      </div>

      {counts && total > 0 && (
        <div
          role="progressbar"
          aria-label="Processing progress"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={counts.completed}
          className="mt-3 flex h-1.5 w-full overflow-hidden rounded-full bg-navy-800"
        >
          <div className="bg-processed" style={{ width: pct(counts.completed, total) }} />
          <div
            className="animate-pulse bg-unresolved"
            style={{ width: pct(counts.processing, total) }}
          />
          <div className="bg-failed" style={{ width: pct(counts.failed, total) }} />
          <div className="bg-navy-600" style={{ width: pct(counts.pending, total) }} />
        </div>
      )}

      {unprocessable > 0 && (
        <p className="mt-2 text-xs text-slate-500">
          {unprocessable} pending file{unprocessable === 1 ? "" : "s"} cannot be processed
          yet: no extractor exists for {unprocessable === 1 ? "its" : "their"} file type in
          this release.
        </p>
      )}

      {error && (
        <p role="alert" className="mt-2 text-xs text-failed">
          {error}{" "}
          <button type="button" onClick={onRefresh} className="underline underline-offset-2">
            Try again
          </button>
        </p>
      )}
    </div>
  );
}
