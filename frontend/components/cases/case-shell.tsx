"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import clsx from "clsx";
import {
  AlertTriangle,
  Archive,
  ArrowLeft,
  ClipboardCheck,
  Files,
  LayoutDashboard,
  Network,
  Pencil,
  Quote,
  Tags,
  Trash2,
} from "lucide-react";
import { archiveCase, deleteCase, getCase, updateCase } from "@/lib/api/cases";
import type { Case } from "@/lib/types/case";
import { CaseForm } from "@/components/cases/case-form";
import { StatusBadge } from "@/components/ui/status-badge";
import type { AnalysisRun } from "@/lib/types/analysis";
import { RunAnalysis } from "@/components/analysis/run-analysis";
import { analysisPhase, type AnalysisPhase } from "@/components/analysis/analysis-state";
import { BUTTON, INPUT, TAB_BAR, TAB_ITEM } from "@/components/ui/primitives";
import { useReviewer } from "@/hooks/use-reviewer";

interface CaseContextValue {
  caseItem: Case;
  /** Bumped after an analysis run finishes, so open pages can reload. */
  analysisVersion: number;
  /** The latest analysis run as reported by the backend (null = never analysed). */
  analysisRun: AnalysisRun | null;
  /** never | running | completed | failed, or unknown until the status has loaded. */
  analysisPhase: AnalysisPhase;
}

const CaseContext = createContext<CaseContextValue | null>(null);

export function useCaseContext(): CaseContextValue {
  const value = useContext(CaseContext);
  if (!value) throw new Error("useCaseContext must be used inside CaseShell");
  return value;
}

const NAV = [
  { href: "", label: "Overview", icon: LayoutDashboard },
  { href: "/evidence", label: "Evidence", icon: Files },
  { href: "/claims", label: "Claims", icon: Quote },
  { href: "/entities", label: "Entities", icon: Tags },
  { href: "/contradictions", label: "Contradictions", icon: AlertTriangle },
  { href: "/graph", label: "Graph", icon: Network },
  { href: "/review", label: "Review queue", icon: ClipboardCheck },
];

export function CaseShell({ caseId, children }: { caseId: string; children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [item, setItem] = useState<Case | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "missing">("loading");
  const [editing, setEditing] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [analysisVersion, setAnalysisVersion] = useState(0);
  const [analysisRun, setAnalysisRun] = useState<AnalysisRun | null>(null);
  const [analysisLoaded, setAnalysisLoaded] = useState(false);
  const [reviewer, setReviewer] = useReviewer();
  const handleRun = useCallback((run: AnalysisRun | null) => {
    setAnalysisRun(run);
    setAnalysisLoaded(true);
  }, []);

  const load = useCallback(async () => {
    try {
      setItem(await getCase(caseId));
      setState("ready");
    } catch {
      setState("missing");
    }
  }, [caseId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function toggleArchive() {
    if (!item) return;
    setBusy(true);
    try {
      if (item.status === "archived") await updateCase(item.id, { status: "open" });
      else await archiveCase(item.id);
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!item) return;
    setBusy(true);
    try {
      await deleteCase(item.id);
      router.push("/cases");
    } finally {
      setBusy(false);
    }
  }

  if (state === "loading") return <p className="text-sm text-slate-500">Loading case…</p>;
  if (state === "missing" || !item) {
    return (
      <div>
        <BackLink />
        <p className="mt-6 text-sm text-slate-400">This case could not be found.</p>
      </div>
    );
  }

  const root = `/cases/${caseId}`;
  const active = (href: string) =>
    href === "" ? pathname === root : pathname === root + href || pathname.startsWith(`${root + href}/`);

  return (
    <CaseContext.Provider
      value={{
        caseItem: item,
        analysisVersion,
        analysisRun,
        analysisPhase: analysisPhase(analysisRun, analysisLoaded),
      }}
    >
      <BackLink />
      {/* Title on the left, actions in one right-aligned column. Below lg the actions
          stack under the title, left-aligned, instead of floating mid-page. */}
      <header className="mt-3 grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-3">
            <h1 className="truncate text-2xl font-semibold tracking-tight text-slate-100">
              {item.title}
            </h1>
            <StatusBadge status={item.status} />
          </div>
          {item.description && (
            <p className="mt-1 max-w-3xl text-sm text-slate-400">{item.description}</p>
          )}
        </div>
        <div className="flex flex-col items-start gap-2 lg:items-end" data-testid="case-actions">
          <RunAnalysis
            caseId={caseId}
            onDone={() => setAnalysisVersion((n) => n + 1)}
            onRun={handleRun}
          />
          <div className="flex flex-wrap items-center justify-start gap-1.5 lg:justify-end">
            <label className="flex items-center gap-1.5 text-xs text-slate-500">
              Reviewer
              <input
                value={reviewer}
                onChange={(e) => setReviewer(e.target.value)}
                placeholder="your name"
                className={`${INPUT} w-32 py-1 text-xs`}
                aria-label="Reviewer name recorded with review decisions"
              />
            </label>
            <button type="button" onClick={() => setEditing((v) => !v)} className={BUTTON}>
              <Pencil className="h-3.5 w-3.5" aria-hidden /> {editing ? "Cancel" : "Edit"}
            </button>
            <button type="button" onClick={() => void toggleArchive()} disabled={busy} className={BUTTON}>
              <Archive className="h-3.5 w-3.5" aria-hidden />
              {item.status === "archived" ? "Unarchive" : "Archive"}
            </button>
            <button
              type="button"
              onClick={() => setConfirmingDelete(true)}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-md border border-failed/40 px-3 py-1.5 text-xs text-failed hover:bg-failed/10 disabled:opacity-50"
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden /> Delete
            </button>
          </div>
        </div>
      </header>

      {editing && (
        <section className="mt-4 rounded-lg border border-navy-800 bg-navy-900 p-5">
          <h2 className="mb-4 text-sm font-medium text-slate-200">Edit case</h2>
          <CaseForm
            existing={item}
            onDone={() => {
              setEditing(false);
              void load();
            }}
          />
        </section>
      )}

      {confirmingDelete && (
        <div
          role="alertdialog"
          aria-label="Confirm delete"
          className="mt-4 rounded-lg border border-failed/40 bg-charcoal-800 p-5"
        >
          <p className="text-sm text-slate-200">
            Permanently delete <strong>{item.title}</strong>? This removes the case and all of
            its evidence, extractions, claims and review history. It cannot be undone.
          </p>
          <div className="mt-4 flex gap-2">
            <button
              type="button"
              onClick={() => void remove()}
              disabled={busy}
              className="rounded-md bg-failed px-4 py-2 text-sm font-medium text-navy-950 hover:opacity-90 disabled:opacity-50"
            >
              {busy ? "Deleting…" : "Yes, delete permanently"}
            </button>
            <button
              type="button"
              onClick={() => setConfirmingDelete(false)}
              disabled={busy}
              className="rounded-md border border-navy-700 px-4 py-2 text-sm text-slate-200 hover:bg-navy-800"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <nav aria-label="Case sections" className={clsx("mt-5", TAB_BAR)}>
        {NAV.map(({ href, label, icon: Icon }) => (
          <Link
            key={label}
            href={root + href}
            aria-current={active(href) ? "page" : undefined}
            className={clsx(
              TAB_ITEM,
              "inline-flex items-center gap-1.5",
              active(href)
                ? "border-slate-200 text-slate-100"
                : "border-transparent text-slate-400 hover:text-slate-200",
            )}
          >
            <Icon className="h-4 w-4" aria-hidden />
            {label}
          </Link>
        ))}
      </nav>

      <div className="mt-6">{children}</div>
    </CaseContext.Provider>
  );
}

function BackLink() {
  return (
    <Link href="/cases" className="inline-flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200">
      <ArrowLeft className="h-4 w-4" aria-hidden /> All cases
    </Link>
  );
}
