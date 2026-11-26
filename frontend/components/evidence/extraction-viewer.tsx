"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Loader2, X } from "lucide-react";
import { isAbortError } from "@/lib/api/client";
import { listExtractions, listSegments } from "@/lib/api/processing";
import { formatDateTime, formatDurationMs } from "@/lib/format";
import type { Extraction, SegmentList } from "@/lib/types/processing";
import { metadataHighlights } from "@/components/evidence/segment-data";
import { SegmentItem } from "@/components/evidence/segment-item";
import { errorCodeLabel, outcomeLabel } from "@/components/evidence/processing-labels";
import { TranscriptBadges } from "@/components/evidence/audio-segment";
import { VERIFY_NOTICE, isAudioTranscript } from "@/components/evidence/audio-transcript";
import { useSegmentPlayer } from "@/hooks/use-segment-player";

const PAGE_SIZE = 25;

interface Props {
  caseId: string;
  evidenceId: string;
  /** Changes when processing for this item settles, so the history reloads. */
  refreshToken: number;
  /** Omit when the viewer is embedded (for example in the evidence workspace). */
  onClose?: () => void;
}

interface LoadedSegments {
  runId: string;
  offset: number;
  list: SegmentList;
}

/** The run to show first: the current run, else the newest successful one. */
function defaultRunId(runs: Extraction[]): string | null {
  return (
    runs.find((r) => r.is_current)?.id ??
    runs.find((r) => r.run_status === "completed")?.id ??
    runs[0]?.id ??
    null
  );
}

export function ExtractionViewer({ caseId, evidenceId, refreshToken, onClose }: Props) {
  const [runs, setRuns] = useState<Extraction[] | null>(null);
  const [runsLoading, setRunsLoading] = useState(true);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [runsReload, setRunsReload] = useState(0);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);

  const [loaded, setLoaded] = useState<LoadedSegments | null>(null);
  const [segLoading, setSegLoading] = useState(false);
  const [segError, setSegError] = useState<string | null>(null);
  const [segReload, setSegReload] = useState(0);

  const player = useSegmentPlayer(caseId, evidenceId);

  const selectedIdRef = useRef<string | null>(null);
  const lastTokenRef = useRef(refreshToken);
  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  // --- run history ----------------------------------------------------------------
  useEffect(() => {
    const controller = new AbortController();
    // A new token means processing just finished: jump to the newest current run.
    const tokenChanged = lastTokenRef.current !== refreshToken;
    lastTokenRef.current = refreshToken;

    setRunsLoading(true);
    setRunsError(null);
    listExtractions(caseId, evidenceId, controller.signal)
      .then((res) => {
        setRuns(res.items);
        const previous = selectedIdRef.current;
        const keep =
          !tokenChanged && previous !== null && res.items.some((r) => r.id === previous);
        const next = keep ? previous : defaultRunId(res.items);
        if (next !== previous) {
          setSelectedId(next);
          setOffset(0);
        }
      })
      .catch((err: unknown) => {
        if (!isAbortError(err)) setRunsError("Could not load the extraction history.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setRunsLoading(false);
      });
    return () => controller.abort();
  }, [caseId, evidenceId, refreshToken, runsReload]);

  const selected = runs?.find((r) => r.id === selectedId) ?? null;
  const selectedRunId = selected?.id ?? null;
  const selectedStatus = selected?.run_status ?? null;
  const currentRun = runs?.find((r) => r.is_current) ?? null;

  // --- segments of the selected run ---------------------------------------------------
  useEffect(() => {
    if (selectedRunId === null || selectedStatus !== "completed") {
      setLoaded(null);
      setSegError(null);
      setSegLoading(false);
      return;
    }
    const controller = new AbortController();
    setSegLoading(true);
    setSegError(null);
    listSegments(
      caseId,
      evidenceId,
      { extractionId: selectedRunId, limit: PAGE_SIZE, offset },
      controller.signal,
    )
      .then((list) => setLoaded({ runId: selectedRunId, offset, list }))
      .catch((err: unknown) => {
        if (!isAbortError(err)) setSegError("Could not load the extracted segments.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setSegLoading(false);
      });
    return () => controller.abort();
  }, [caseId, evidenceId, selectedRunId, selectedStatus, offset, segReload]);

  function selectRun(id: string) {
    if (id === selectedId) return;
    player.stop();
    setSelectedId(id);
    setOffset(0);
    setLoaded(null);
  }

  // Only show segments that belong to the run and page currently selected.
  const list =
    loaded && loaded.runId === selectedRunId && loaded.offset === offset ? loaded.list : null;
  const highlights = selected ? metadataHighlights(selected.doc_metadata) : [];
  const anyConfidence = list?.items.some((s) => s.engine_confidence !== null) ?? false;
  const audioRun = list?.items.some(isAudioTranscript) ?? false;

  return (
    <section
      aria-label="Extraction viewer"
      className="mt-3 rounded-md border border-navy-800 bg-navy-900/60 p-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-100">Extraction</h3>
          <p className="mt-0.5 text-xs text-slate-500">
            Content extracted from the file is untrusted and is shown as plain text.
          </p>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close extraction viewer"
            className="rounded-md p-1 text-slate-400 hover:bg-navy-800 hover:text-slate-200"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        )}
      </div>

      {runsLoading && !runs && (
        <p className="mt-3 flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading extraction history…
        </p>
      )}

      {runsError && (
        <p role="alert" className="mt-3 text-sm text-failed">
          {runsError}{" "}
          <button
            type="button"
            onClick={() => setRunsReload((n) => n + 1)}
            className="underline underline-offset-2"
          >
            Try again
          </button>
        </p>
      )}

      {runs && runs.length === 0 && !runsError && (
        <p className="mt-3 text-sm text-slate-400">
          No extraction yet. Process this file to create the first run.
        </p>
      )}

      {runs && runs.length > 0 && (
        <>
          {/* Run history */}
          <div className="mt-3">
            <p className="text-xs font-medium text-slate-400">
              Run history ({runs.length} run{runs.length === 1 ? "" : "s"})
            </p>
            <ul className="mt-1.5 flex flex-wrap gap-1.5" aria-label="Extraction runs">
              {runs.map((r) => (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => selectRun(r.id)}
                    aria-pressed={r.id === selectedId}
                    className={
                      r.id === selectedId
                        ? "inline-flex items-center gap-1.5 rounded-md border border-navy-600 bg-navy-700 px-2.5 py-1 text-xs text-slate-100"
                        : "inline-flex items-center gap-1.5 rounded-md border border-navy-800 px-2.5 py-1 text-xs text-slate-300 hover:bg-navy-800"
                    }
                  >
                    <span
                      className={
                        r.run_status === "completed"
                          ? "h-1.5 w-1.5 rounded-full bg-processed"
                          : "h-1.5 w-1.5 rounded-full bg-failed"
                      }
                      aria-hidden
                    />
                    Run {r.run_number}
                    {r.is_current && <span className="text-processed">current</span>}
                    {r.run_status === "failed" && <span className="text-failed">failed</span>}
                  </button>
                </li>
              ))}
            </ul>
          </div>

          {/* Selected run */}
          {selected && (
            <div className="mt-4">
              {!selected.is_current && selected.run_status === "completed" && (
                <p className="mb-3 rounded-md bg-navy-800 px-3 py-2 text-xs text-slate-300">
                  This is an earlier run kept for history.{" "}
                  {currentRun
                    ? `The current run is Run ${currentRun.run_number}.`
                    : "There is no current run."}
                </p>
              )}

              <div className="flex flex-wrap items-center gap-2">
                <h4 className="text-sm font-medium text-slate-100">Run {selected.run_number}</h4>
                {selected.is_current && (
                  <span className="rounded-full bg-processed/15 px-2 py-0.5 text-xs text-processed">
                    Current
                  </span>
                )}
                <span
                  className={
                    selected.run_status === "completed"
                      ? "rounded-full bg-navy-700 px-2 py-0.5 text-xs text-unresolved"
                      : "rounded-full bg-failed/15 px-2 py-0.5 text-xs text-failed"
                  }
                >
                  {selected.run_status}
                </span>
                {selected.outcome && (
                  <span className="rounded-full bg-navy-700 px-2 py-0.5 text-xs text-unresolved">
                    {outcomeLabel(selected.outcome)}
                  </span>
                )}
              </div>

              <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-3">
                <Fact label="Extractor">
                  {selected.extractor} v{selected.extractor_version}
                </Fact>
                <Fact label="Extracted at">{formatDateTime(selected.recorded_at)}</Fact>
                <Fact label="Duration">{formatDurationMs(selected.duration_ms)}</Fact>
                <Fact label="Segments">{selected.segment_count}</Fact>
                <Fact label="Source hash (SHA-256)">
                  <span className="font-mono" title={selected.source_sha256}>
                    {selected.source_sha256.slice(0, 12)}…
                  </span>
                </Fact>
                {highlights.map((h) => (
                  <Fact key={h.label} label={h.label}>
                    {h.value}
                  </Fact>
                ))}
              </dl>

              {selected.run_status === "failed" && (
                <div role="alert" className="mt-3 rounded-md border border-failed/40 bg-failed/10 p-3">
                  <p className="text-sm font-medium text-failed">
                    This run failed
                    {errorCodeLabel(selected.error_code)
                      ? `: ${errorCodeLabel(selected.error_code)}`
                      : ""}
                  </p>
                  {selected.error_message && (
                    <p className="mt-1 whitespace-pre-wrap break-words text-sm text-slate-300">
                      {selected.error_message}
                    </p>
                  )}
                  <p className="mt-1 text-xs text-slate-500">
                    A failed run produces no segments. Earlier successful runs are unaffected.
                  </p>
                </div>
              )}

              {selected.warnings.length > 0 && (
                <div className="mt-3 rounded-md border border-navy-700 bg-navy-800/60 p-3">
                  <p className="text-xs font-medium text-slate-300">
                    Warnings ({selected.warnings.length})
                  </p>
                  <ul className="mt-1 space-y-1.5">
                    {selected.warnings.map((w, i) => (
                      <li key={`${i}-${w.code}`} className="text-xs text-slate-300">
                        <span className="mr-1.5 rounded bg-navy-700 px-1.5 py-0.5 font-mono text-slate-400">
                          {w.code}
                        </span>
                        <span className="whitespace-pre-wrap break-words">{w.message}</span>
                        {w.detail && (
                          <details className="mt-1 text-slate-500">
                            <summary className="cursor-pointer">Details</summary>
                            <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-words rounded bg-navy-950 p-2 text-[11px]">
                              {JSON.stringify(w.detail, null, 2)}
                            </pre>
                          </details>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <details className="mt-3 text-xs text-slate-500">
                <summary className="cursor-pointer text-slate-400">Run metadata</summary>
                <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-navy-950 p-2 text-[11px]">
                  {JSON.stringify(selected.doc_metadata, null, 2)}
                </pre>
              </details>

              {/* Segments */}
              {selected.run_status === "completed" && (
                <div className="mt-4">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-medium text-slate-400">
                      Segments ({list?.total ?? selected.segment_count})
                    </p>
                    {segLoading && (
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-500" aria-hidden />
                    )}
                  </div>

                  {segError && (
                    <p role="alert" className="mt-2 text-sm text-failed">
                      {segError}{" "}
                      <button
                        type="button"
                        onClick={() => setSegReload((n) => n + 1)}
                        className="underline underline-offset-2"
                      >
                        Try again
                      </button>
                    </p>
                  )}

                  {!list && segLoading && !segError && (
                    <p className="mt-2 text-sm text-slate-500">Loading segments…</p>
                  )}

                  {list && list.total === 0 && (
                    <p className="mt-2 text-sm text-slate-400">
                      This run produced no segments
                      {selected.outcome === "empty" ? " (no extractable content)." : "."}
                    </p>
                  )}

                  {list && list.items.length > 0 && audioRun && (
                    <div
                      role="note"
                      className="mt-2 rounded-md border border-navy-700 bg-navy-800/60 p-3 text-xs text-slate-300"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <TranscriptBadges reviewStatus="unreviewed" />
                      </div>
                      <p className="mt-1.5">{VERIFY_NOTICE}</p>
                      <p className="mt-1 text-slate-500">
                        The text below is the original machine output. It is never edited;
                        human corrections are stored separately and shown in the evidence
                        workspace.
                      </p>
                      {player.error && (
                        <p role="alert" className="mt-1.5 text-failed">
                          {player.error}
                        </p>
                      )}
                    </div>
                  )}

                  {list && list.items.length > 0 && (
                    <>
                      <ul className="mt-2 space-y-2" aria-label="Extracted segments">
                        {list.items.map((s) => (
                          <SegmentItem
                            key={s.id}
                            segment={s}
                            playback={
                              s.locator.kind === "audio" && player.state !== "unsupported"
                                ? {
                                    active: player.activeSeq === s.seq,
                                    loading: player.state === "loading",
                                    onPlay: () =>
                                      s.locator.kind === "audio" &&
                                      player.play(s.seq, s.locator.start, s.locator.end),
                                    onStop: player.stop,
                                  }
                                : undefined
                            }
                          />
                        ))}
                      </ul>
                      {anyConfidence && (
                        <p className="mt-2 text-xs text-slate-500">
                          Confidence values are reported by the extraction engine. They are not a
                          measure of factual accuracy.
                        </p>
                      )}
                      {list.total > PAGE_SIZE && (
                        <div className="mt-3 flex items-center justify-between text-xs text-slate-400">
                          <button
                            type="button"
                            disabled={offset === 0 || segLoading}
                            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                            className="inline-flex items-center gap-1 rounded-md border border-navy-700 px-2.5 py-1 hover:bg-navy-800 disabled:opacity-40"
                          >
                            <ChevronLeft className="h-3.5 w-3.5" aria-hidden /> Previous
                          </button>
                          <span>
                            {list.offset + 1}–{Math.min(list.offset + list.items.length, list.total)}{" "}
                            of {list.total}
                          </span>
                          <button
                            type="button"
                            disabled={offset + PAGE_SIZE >= list.total || segLoading}
                            onClick={() => setOffset((o) => o + PAGE_SIZE)}
                            className="inline-flex items-center gap-1 rounded-md border border-navy-700 px-2.5 py-1 hover:bg-navy-800 disabled:opacity-40"
                          >
                            Next <ChevronRight className="h-3.5 w-3.5" aria-hidden />
                          </button>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-slate-500">{label}</dt>
      <dd className="break-words text-slate-200">{children}</dd>
    </div>
  );
}
