"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Progress } from "@/lib/browser-processing/run";
import type { Evidence } from "@/lib/types/evidence";

export interface BrowserJob {
  evidenceId: string;
  progress: Progress;
}

export interface UseBrowserProcessing {
  /** The file being processed in this tab, if any (one at a time, to bound memory). */
  job: BrowserJob | null;
  /** Last error per evidence id, until the next attempt. */
  errors: Readonly<Record<string, string>>;
  start: (evidence: Evidence, force: boolean) => void;
  cancel: () => void;
}

/**
 * Runs in-browser processing for one file at a time. The engines are loaded only when
 * the first file is processed (`import()` of lib/browser-processing/run). While a job
 * runs, closing or reloading the tab asks for confirmation.
 *
 * `onFinished` is called after every attempt (success or failure) so the caller can
 * reload the server's status; "Completed" is only ever shown from that status.
 */
export function useBrowserProcessing(
  caseId: string,
  onFinished: (evidenceId: string) => void,
): UseBrowserProcessing {
  const [job, setJob] = useState<BrowserJob | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const controller = useRef<AbortController | null>(null);
  const finishedRef = useRef(onFinished);
  useEffect(() => {
    finishedRef.current = onFinished;
  });

  useEffect(() => {
    if (!job) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = ""; // the browser shows its own "leave this page?" prompt
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [job]);

  // Leaving the page (client-side navigation) cancels the job, which reports it.
  useEffect(() => () => controller.current?.abort(), []);

  const start = useCallback(
    (evidence: Evidence, force: boolean) => {
      if (controller.current) return;
      const ctl = new AbortController();
      controller.current = ctl;
      const id = evidence.id;
      setErrors((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      setJob({ evidenceId: id, progress: { phase: "checking", fraction: null } });
      void (async () => {
        try {
          const { processInBrowser } = await import("@/lib/browser-processing/run");
          await processInBrowser({
            caseId,
            evidence,
            force,
            signal: ctl.signal,
            onProgress: (progress) => setJob({ evidenceId: id, progress }),
          });
        } catch (err) {
          const message = err instanceof Error && err.message ? err.message : "In-browser processing failed.";
          setErrors((prev) => ({ ...prev, [id]: message }));
        } finally {
          controller.current = null;
          setJob(null);
          finishedRef.current(id);
        }
      })();
    },
    [caseId],
  );

  const cancel = useCallback(() => controller.current?.abort(), []);

  return { job, errors, start, cancel };
}
