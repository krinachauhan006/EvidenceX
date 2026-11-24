"use client";

import { useEffect, useState } from "react";
import { ApiError, isAbortError } from "@/lib/api/client";

/**
 * Fetch a Blob and expose it as an object URL that is revoked on change/unmount.
 * Used for previews of the original evidence, served by case-scoped endpoints.
 */
export function useObjectUrl(
  load: ((signal: AbortSignal) => Promise<Blob>) | null,
  deps: readonly unknown[],
): { url: string | null; error: string | null; loading: boolean } {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!load) {
      setUrl(null);
      return;
    }
    const controller = new AbortController();
    let created: string | null = null;
    setLoading(true);
    setError(null);
    load(controller.signal)
      .then((blob) => {
        created = URL.createObjectURL(blob);
        setUrl(created);
      })
      .catch((err: unknown) => {
        if (isAbortError(err)) return;
        setUrl(null);
        setError(
          err instanceof ApiError && err.status === 404
            ? "The original file or page could not be found."
            : "The preview could not be loaded.",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => {
      controller.abort();
      if (created) URL.revokeObjectURL(created);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { url, error, loading };
}
