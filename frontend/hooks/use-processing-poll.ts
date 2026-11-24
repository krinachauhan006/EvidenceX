"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { isAbortError } from "@/lib/api/client";
import { getCaseProcessing } from "@/lib/api/processing";
import type { CaseProcessingSummary } from "@/lib/types/processing";

// How often to ask for status while work is active.
const DEFAULT_INTERVAL_MS = 2000;
// A queued item that shows no sign of starting for this long is given up on, so
// polling cannot run forever if a background job never started.
const DEFAULT_QUEUE_GRACE_MS = 15000;
const MAX_CONSECUTIVE_ERRORS = 3;
const MAX_BACKOFF_MS = 10000;

const EMPTY_SET: ReadonlySet<string> = new Set();

export interface UseProcessingPollOptions {
  intervalMs?: number;
  queueGraceMs?: number;
  /**
   * Called once when items finish a processing attempt (completed or failed), so
   * the caller can reload evidence and extraction data.
   */
  onSettled?: (evidenceIds: string[]) => void;
}

export interface UseProcessingPoll {
  summary: CaseProcessingSummary | null;
  /** True until the first status request finishes. */
  loading: boolean;
  /** Set when the first load failed or live updates were given up on. */
  error: string | null;
  /** True while status is being polled because work is active. */
  polling: boolean;
  /** Items accepted by the server that have not started processing yet. */
  queuedIds: ReadonlySet<string>;
  /** Tell the hook that these items were just queued; starts polling. */
  markQueued: (evidenceIds: string[]) => void;
  /** Fetch status now (shares an in-flight request) and clear any error. */
  refresh: () => Promise<void>;
}

interface Controls {
  refresh: () => Promise<void>;
  markQueued: (ids: string[]) => void;
}

/**
 * Polls case processing status only while something is processing or queued.
 *
 * - One request at a time: the next poll is scheduled when the previous one ends,
 *   and concurrent callers share the in-flight request.
 * - Stops on its own once nothing is processing and no queued item is waiting.
 * - Aborts the request and clears timers on unmount or case change.
 * - API errors never throw to the caller: after a few consecutive failures polling
 *   stops and `error` is set; `refresh()` starts it again.
 */
export function useProcessingPoll(
  caseId: string,
  options: UseProcessingPollOptions = {},
): UseProcessingPoll {
  const { intervalMs = DEFAULT_INTERVAL_MS, queueGraceMs = DEFAULT_QUEUE_GRACE_MS } = options;

  const [summary, setSummary] = useState<CaseProcessingSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);
  const [queuedIds, setQueuedIds] = useState<ReadonlySet<string>>(EMPTY_SET);

  // Always call the latest callback without restarting the polling effect.
  const onSettledRef = useRef(options.onSettled);
  useEffect(() => {
    onSettledRef.current = options.onSettled;
  });

  const controlsRef = useRef<Controls | null>(null);

  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let controller: AbortController | null = null;
    let inFlight: Promise<void> | null = null;
    let errors = 0;
    let lastProgress = Date.now();
    let current: CaseProcessingSummary | null = null;
    let queueKey = "";
    // evidence id -> attempt count when it was queued
    const queue = new Map<string, number>();

    setSummary(null);
    setLoading(true);
    setError(null);
    setPolling(false);
    setQueuedIds(EMPTY_SET);

    const clearTimer = () => {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
    };

    const publishQueue = () => {
      const key = [...queue.keys()].sort().join(",");
      if (key !== queueKey) {
        queueKey = key;
        setQueuedIds(new Set(queue.keys()));
      }
    };

    const isActive = () => {
      if (!current) return false;
      if (current.counts.processing > 0) return true;
      return queue.size > 0 && Date.now() - lastProgress < queueGraceMs;
    };

    const schedule = () => {
      clearTimer();
      if (!live) return;
      if (errors >= MAX_CONSECUTIVE_ERRORS || !isActive()) {
        setPolling(false);
        return;
      }
      setPolling(true);
      const delay =
        errors > 0 ? Math.min(intervalMs * 2 ** errors, MAX_BACKOFF_MS) : intervalMs;
      timer = setTimeout(() => {
        void run();
      }, delay);
    };

    const apply = (next: CaseProcessingSummary) => {
      const before = new Map((current?.items ?? []).map((i) => [i.evidence_id, i]));
      const present = new Set<string>();
      const settled: string[] = [];
      let progressed = false;

      for (const item of next.items) {
        present.add(item.evidence_id);
        const prev = before.get(item.evidence_id);
        if (!prev || prev.status !== item.status || prev.attempts !== item.attempts) {
          progressed = true;
        }
        const terminal = item.status === "completed" || item.status === "failed";
        const baseline = queue.get(item.evidence_id);
        if (baseline !== undefined) {
          // A queued item is done once an attempt that began after queuing finished.
          if (terminal && item.attempts > baseline) {
            queue.delete(item.evidence_id);
            settled.push(item.evidence_id);
          }
        } else if (prev?.status === "processing" && terminal) {
          settled.push(item.evidence_id);
        }
      }

      // Items deleted while queued.
      for (const id of [...queue.keys()]) {
        if (!present.has(id)) queue.delete(id);
      }
      if (progressed) lastProgress = Date.now();
      // Nothing started within the grace period: stop waiting.
      if (
        queue.size > 0 &&
        next.counts.processing === 0 &&
        Date.now() - lastProgress >= queueGraceMs
      ) {
        queue.clear();
      }

      current = next;
      setSummary(next);
      publishQueue();
      if (settled.length > 0) onSettledRef.current?.(settled);
    };

    const run = (): Promise<void> => {
      if (!live) return Promise.resolve();
      if (inFlight) return inFlight; // never two requests at once
      controller = new AbortController();
      const signal = controller.signal;
      inFlight = (async () => {
        try {
          const next = await getCaseProcessing(caseId, signal);
          if (!live) return;
          errors = 0;
          setError(null);
          apply(next);
        } catch (err) {
          if (!live || isAbortError(err)) return;
          errors += 1;
          if (current === null) {
            setError("Could not load processing status. Is the backend running?");
          } else if (errors >= MAX_CONSECUTIVE_ERRORS) {
            setError("Live status updates stopped. Check that the backend is running.");
          }
        } finally {
          inFlight = null;
          if (live) {
            setLoading(false);
            schedule();
          }
        }
      })();
      return inFlight;
    };

    controlsRef.current = {
      refresh: () => {
        errors = 0;
        setError(null);
        return run();
      },
      markQueued: (ids) => {
        const attempts = new Map((current?.items ?? []).map((i) => [i.evidence_id, i.attempts]));
        for (const id of ids) queue.set(id, attempts.get(id) ?? 0);
        lastProgress = Date.now();
        publishQueue();
        setPolling(true);
        void run();
      },
    };

    void run();

    return () => {
      live = false;
      clearTimer();
      controller?.abort();
      controlsRef.current = null;
    };
  }, [caseId, intervalMs, queueGraceMs]);

  const refresh = useCallback(() => controlsRef.current?.refresh() ?? Promise.resolve(), []);
  const markQueued = useCallback((ids: string[]) => {
    controlsRef.current?.markQueued(ids);
  }, []);

  return { summary, loading, error, polling, queuedIds, markQueued, refresh };
}
