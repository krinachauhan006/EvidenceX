"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { ApiError } from "@/lib/api/client";
import { login, register, safeNext } from "@/lib/api/auth";
import { Brand } from "@/components/layout/brand";
import { health, serverNotice } from "@/lib/api/health";
import { PASSWORD_MIN, passwordLength, passwordProblem } from "@/lib/password-policy";
import { PasswordField } from "./password-field";

const INPUT =
  "w-full rounded-md border border-navy-700 bg-navy-950/80 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-sky-500/60 focus:outline-none focus:ring-1 focus:ring-sky-500/40 aria-[invalid=true]:border-failed/60";
const FIELD = `mt-1 ${INPUT}`;

/** A readable message for a failed sign-in or registration. */
export function authErrorText(err: unknown, mode: "login" | "register"): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return "The EvidenceX API could not be reached.";
    if (err.status === 429) return "Too many attempts. Wait a minute and try again.";
    if (typeof err.detail === "string" && err.detail) return err.detail;
    if (Array.isArray(err.detail)) {
      const first = err.detail[0] as { msg?: unknown } | undefined;
      if (first && typeof first.msg === "string") return first.msg.replace(/^Value error, /, "");
    }
    if (mode === "login" && err.status === 401) return "The e-mail or password is not correct.";
    if (err.status >= 500) return "The EvidenceX server could not complete the request. Check the backend log.";
  }
  return mode === "login" ? "Sign-in failed." : "The account could not be created.";
}

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [claimed, setClaimed] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [pwError, setPwError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Tell people up front when the server cannot serve accounts (e.g. a pending
  // database migration), instead of letting every attempt fail with a generic error.
  useEffect(() => {
    const c = new AbortController();
    health(c.signal)
      .then((h) => setNotice(serverNotice(h)))
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 0) setNotice("The EvidenceX API could not be reached.");
      });
    return () => c.abort();
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (mode === "register") {
      // Same rule as the server; the server still checks and is the authority.
      const problem = passwordProblem(password);
      setPwError(problem);
      if (problem) return;
    }
    setRevealed(false); // never leave a password visible behind a page change
    setBusy(true);
    try {
      const session =
        mode === "login"
          ? await login({ email, password })
          : await register({ email, display_name: name, password });
      if (session.claimed_cases > 0) {
        setClaimed(session.claimed_cases);
        setTimeout(() => router.replace(next), 1800);
      } else {
        router.replace(next);
      }
    } catch (err) {
      setError(authErrorText(err, mode));
      setBusy(false);
    }
  }

  const other = mode === "login" ? "/register" : "/login";
  const keep = next !== "/cases" ? `?next=${encodeURIComponent(next)}` : "";
  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-navy-950 px-4 py-10">
      <div aria-hidden className="pointer-events-none absolute inset-0 bg-[radial-gradient(60rem_30rem_at_50%_-10%,rgba(56,189,248,0.12),transparent)]" />
      <div className="relative w-full max-w-sm">
        <Brand className="mb-8 justify-center" />
        <div className="rounded-xl border border-white/10 bg-navy-900/80 p-6 shadow-2xl shadow-black/40 backdrop-blur">
          <h1 className="text-lg font-semibold text-slate-50">
            {mode === "login" ? "Sign in to your workspace" : "Create your account"}
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            {mode === "login"
              ? "Your cases are visible only to you and the people you add."
              : "Accounts are stored on this EvidenceX server only."}
          </p>
          {notice && (
            <p role="alert" className="mt-4 rounded-md border border-failed/30 bg-failed/10 px-3 py-2 text-sm text-slate-100" data-testid="server-notice">
              {notice}
            </p>
          )}
          <form onSubmit={(e) => void submit(e)} className="mt-5 space-y-4" noValidate>
            {mode === "register" && (
              <label className="block text-xs font-medium text-slate-300">
                Display name
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  maxLength={128}
                  autoComplete="name"
                  className={FIELD}
                />
              </label>
            )}
            <label className="block text-xs font-medium text-slate-300">
              E-mail
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                maxLength={254}
                autoComplete="email"
                className={FIELD}
              />
            </label>
            <PasswordField
              label="Password"
              value={password}
              onChange={(v) => {
                setPassword(v);
                if (pwError) setPwError(passwordProblem(v));
              }}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              inputClassName={INPUT}
              revealed={revealed}
              onRevealedChange={setRevealed}
              invalid={mode === "register" && pwError !== null}
              describedBy={pwError ? "password-error" : undefined}
              hint={
                mode === "register" ? (
                  <>
                    At least {PASSWORD_MIN} characters.{" "}
                    <span className="tabular-nums" data-testid="password-count">
                      {passwordLength(password)}/{PASSWORD_MIN}
                    </span>
                  </>
                ) : undefined
              }
            />
            {mode === "register" && pwError && (
              <p id="password-error" role="alert" className="-mt-2 text-xs text-failed" data-testid="password-error">
                {pwError}
              </p>
            )}
            {error && (
              <p role="alert" className="rounded-md border border-failed/30 bg-failed/10 px-3 py-2 text-sm text-failed">
                {error}
              </p>
            )}
            {claimed > 0 && (
              <p role="status" className="rounded-md border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-sm text-sky-200">
                This is the account the server operator designated for earlier data: you now own{" "}
                {claimed} case{claimed === 1 ? "" : "s"} created before sign-in was added. This was
                recorded in each case&apos;s audit trail.
              </p>
            )}
            <button
              type="submit"
              disabled={busy}
              className="flex w-full items-center justify-center gap-2 rounded-md bg-sky-500 px-4 py-2 text-sm font-semibold text-navy-950 hover:bg-sky-400 disabled:opacity-60"
            >
              {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
              {mode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>
        </div>
        <p className="mt-5 text-center text-sm text-slate-400">
          {mode === "login" ? "New to EvidenceX? " : "Already have an account? "}
          <Link href={other + keep} className="font-medium text-sky-300 hover:text-sky-200">
            {mode === "login" ? "Create an account" : "Sign in"}
          </Link>
        </p>
        <p className="mt-2 text-center text-xs text-slate-400">
          <Link href="/" className="hover:text-slate-200">
            Back to the overview
          </Link>
        </p>
      </div>
    </div>
  );
}
