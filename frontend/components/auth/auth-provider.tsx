"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { ApiError } from "@/lib/api/client";
import { logout as apiLogout, me } from "@/lib/api/auth";
import type { User } from "@/lib/types/phase2";

interface AuthValue {
  user: User;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthGate");
  return value;
}

/**
 * Client-side session gate for the signed-in area. The API is the authority: every
 * endpoint checks the session cookie itself and returns 401/403/404. This gate only
 * decides what to render, so a visitor without a session is sent to /login instead
 * of seeing empty screens. (A Next.js middleware cannot do this check reliably: the
 * cookie belongs to the API's host, which may differ from the frontend's.)
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [state, setState] = useState<"checking" | "ready" | "offline">("checking");
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    me(controller.signal)
      .then((u) => {
        setUser(u);
        setState("ready");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        if (err instanceof ApiError && err.status === 401) {
          // Keep the query too (e.g. ?segment=… on a source link) so sign-in returns
          // to exactly the requested view. /login validates it with safeNext().
          const here = (pathname || "/cases") + window.location.search;
          router.replace(`/login?next=${encodeURIComponent(here)}`);
        } else {
          // The server answered with its own explanation (e.g. 503: a database
          // migration is pending): show that rather than "could not be reached".
          setProblem(err instanceof ApiError && err.status >= 500 && typeof err.detail === "string" ? err.detail : null);
          setState("offline");
        }
      });
    return () => controller.abort();
  }, [router, pathname]);

  const signOut = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      router.replace("/login");
    }
  }, [router]);

  if (state === "offline") {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <div role="alert" className="max-w-md rounded-lg border border-failed/30 bg-failed/10 p-5 text-sm text-failed">
          {problem ??
            "The EvidenceX API could not be reached. Check that the backend is running and that NEXT_PUBLIC_API_BASE_URL points to it, then reload the page."}
        </div>
      </div>
    );
  }
  if (state === "checking" || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden /> Checking your session…
      </div>
    );
  }
  return <AuthContext.Provider value={{ user, signOut }}>{children}</AuthContext.Provider>;
}
