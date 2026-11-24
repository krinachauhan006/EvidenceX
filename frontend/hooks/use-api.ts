"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, isAbortError } from "@/lib/api/client";

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  /** HTTP status of the last failure (0 = network failure), or null when there is none. */
  errorStatus: number | null;
  loading: boolean;
  reload: () => void;
  setData: (value: T) => void;
}

/** Message for a failed request. Server details are shown only when they are text. */
export function errorText(err: unknown, fallback: string): string {
  if (err instanceof ApiError && typeof err.detail === "string" && err.detail) return err.detail;
  return fallback;
}

/**
 * Load data from the typed API client. Cancels the previous request when inputs
 * change and keeps the last good data while reloading.
 */
export function useApi<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
  fallbackError = "Could not load this data.",
): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setErrorStatus(null);
    fetcherRef
      .current(controller.signal)
      .then((value) => setData(value))
      .catch((err: unknown) => {
        if (isAbortError(err)) return;
        setError(errorText(err, fallbackError));
        setErrorStatus(err instanceof ApiError ? err.status : 0);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { data, error, errorStatus, loading, reload, setData };
}
