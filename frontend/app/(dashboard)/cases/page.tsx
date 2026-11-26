"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import clsx from "clsx";
import {
  AlertTriangle,
  ArrowRight,
  ClipboardCheck,
  FolderKanban,
  Loader2,
  Plus,
  Search,
  Waypoints,
  X,
} from "lucide-react";
import { listCases } from "@/lib/api/cases";
import { workspaceSummary } from "@/lib/api/phase2";
import type { Case, CaseStatus } from "@/lib/types/case";
import { formatDateTime } from "@/lib/format";
import { CaseForm } from "@/components/cases/case-form";
import { StatusBadge } from "@/components/ui/status-badge";
import { useAuth } from "@/components/auth/auth-provider";
import { FileTypeIcon } from "@/components/evidence/file-type-icon";
import { Badge, BUTTON_SOLID, Card, EmptyState, ErrorState, INPUT, Skeleton } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { useApi } from "@/hooks/use-api";

const PAGE_SIZE = 24;

export default function CasesPage() {
  const { user } = useAuth();
  const notify = useToast();
  const [cases, setCases] = useState<Case[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [statusFilter, setStatusFilter] = useState<CaseStatus | "all">("open");
  const [query, setQuery] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const summary = useApi((signal) => workspaceSummary(signal), [version]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listCases({
        status: statusFilter === "all" ? undefined : statusFilter,
        limit: PAGE_SIZE,
        offset,
      });
      setCases(res.items);
      setTotal(res.total);
    } catch {
      setError("Could not reach the API. Is the backend running?");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return cases;
    return cases.filter((c) => `${c.title} ${c.description ?? ""}`.toLowerCase().includes(q));
  }, [cases, query]);

  const s = summary.data;
  const active = s?.processing_activity.filter((p) => p.status !== "failed") ?? [];
  const failed = s?.processing_activity.filter((p) => p.status === "failed") ?? [];
  const firstName = user.display_name.split(" ")[0];

  return (
    <div>
      <header className="relative mb-6 overflow-hidden rounded-2xl border border-white/[0.06] bg-gradient-to-br from-navy-900 via-navy-900 to-indigo-950/60 p-6">
        <div aria-hidden className="evx-grid-bg pointer-events-none absolute inset-0 opacity-60" />
        <div className="relative flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.2em] text-sky-300/80">Workspace</p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-50 md:text-3xl">
              Welcome back, {firstName}
            </h1>
            <p className="mt-1 max-w-xl text-sm text-slate-400">
              Your investigations. Each case is visible only to you and the members you add.
            </p>
          </div>
          <button type="button" onClick={() => setShowForm((v) => !v)} className={BUTTON_SOLID} aria-expanded={showForm}>
            {showForm ? <X className="h-4 w-4" aria-hidden /> : <Plus className="h-4 w-4" aria-hidden />}
            {showForm ? "Cancel" : "New investigation"}
          </button>
        </div>
        <div className="relative mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Metric icon={<FolderKanban className="h-4 w-4" aria-hidden />} label="Open cases" value={s?.cases.open} hint={s ? `${s.cases.archived} archived` : undefined} />
          <Metric
            icon={<FileTypeIcon type="document" className="h-4 w-4" />}
            label="Evidence items"
            value={s?.evidence.total}
            hint={s ? `${s.evidence.by_status.completed ?? 0} processed` : undefined}
          />
          <Metric
            icon={<ClipboardCheck className="h-4 w-4" aria-hidden />}
            label="Claims to review"
            value={s?.review.open_claims}
            hint={s ? `${s.review.proposed_events} events proposed` : undefined}
          />
          <Metric
            icon={<AlertTriangle className="h-4 w-4" aria-hidden />}
            label="Possible inconsistencies"
            value={s?.review.open_contradictions}
            hint="awaiting review"
            amber={Boolean(s?.review.open_contradictions)}
          />
        </div>
      </header>

      {showForm && (
        <Card className="evx-page mb-6 p-5">
          <h2 className="mb-4 text-sm font-medium text-slate-200">Start a new investigation</h2>
          <CaseForm
            onDone={() => {
              setShowForm(false);
              setOffset(0);
              void load();
              setVersion((n) => n + 1);
              notify("success", "Investigation created", "You are its owner. Add evidence to begin.");
            }}
          />
        </Card>
      )}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_18rem]">
        <section aria-label="Cases">
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <div className="relative min-w-[12rem] flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-2 h-4 w-4 text-slate-500" aria-hidden />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Filter by title or description"
                className={`${INPUT} py-1.5 pl-8`}
                aria-label="Filter cases"
              />
            </div>
            <div className="flex gap-1 rounded-lg border border-navy-800 p-0.5 text-sm" role="group" aria-label="Case status">
              {(["open", "archived", "all"] as const).map((st) => (
                <button
                  key={st}
                  type="button"
                  aria-pressed={statusFilter === st}
                  onClick={() => {
                    setStatusFilter(st);
                    setOffset(0);
                  }}
                  className={clsx(
                    "rounded-md px-3 py-1 capitalize transition-colors",
                    statusFilter === st ? "bg-navy-700 text-slate-50" : "text-slate-400 hover:text-slate-200",
                  )}
                >
                  {st}
                </button>
              ))}
            </div>
          </div>

          {error && <ErrorState message={error} onRetry={() => void load()} />}
          {!error && loading && <Skeleton rows={3} />}
          {!error && !loading && shown.length === 0 && (
            <EmptyState title={cases.length ? "No cases match the filter" : "No investigations yet"} icon={<FolderKanban className="h-5 w-5" aria-hidden />}>
              {cases.length ? (
                "Clear the filter to see every case."
              ) : (
                <button type="button" className={`${BUTTON_SOLID} mt-3`} onClick={() => setShowForm(true)}>
                  <Plus className="h-4 w-4" aria-hidden /> Start an investigation
                </button>
              )}
            </EmptyState>
          )}
          {!error && !loading && shown.length > 0 && (
            <ul className="grid gap-3 md:grid-cols-2">
              {shown.map((c) => (
                <li key={c.id}>
                  <Link
                    href={`/cases/${c.id}`}
                    className="evx-card-hover group flex h-full flex-col rounded-xl border border-white/[0.06] bg-navy-900/70 p-4 hover:border-sky-500/30"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="line-clamp-2 font-medium text-slate-50">{c.title}</p>
                      <StatusBadge status={c.status} />
                    </div>
                    {c.description && <p className="mt-1 line-clamp-2 text-sm text-slate-400">{c.description}</p>}
                    <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-3 text-xs text-slate-500">
                      {c.my_role && <Badge>{c.my_role}</Badge>}
                      {c.ai_processing_allowed && <Badge tone="blue">AI allowed</Badge>}
                      <span>Updated {formatDateTime(c.updated_at)}</span>
                      <ArrowRight className="ml-auto h-4 w-4 text-slate-600 transition-transform group-hover:translate-x-0.5 group-hover:text-sky-300" aria-hidden />
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}

          {!error && total > PAGE_SIZE && (
            <div className="mt-4 flex items-center justify-between text-sm text-slate-400">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                className="rounded-md px-3 py-1 hover:text-slate-200 disabled:opacity-40"
              >
                Previous
              </button>
              <span>
                {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
              </span>
              <button
                type="button"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset((o) => o + PAGE_SIZE)}
                className="rounded-md px-3 py-1 hover:text-slate-200 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          )}
        </section>

        <aside className="space-y-4">
          <Card className="p-4">
            <p className="flex items-center gap-1.5 text-sm font-medium text-slate-200">
              <Loader2 className={clsx("h-4 w-4", active.length ? "animate-spin text-sky-300" : "text-slate-600")} aria-hidden />
              Processing activity
            </p>
            {!s && <Skeleton rows={1} className="mt-2" />}
            {s && active.length === 0 && failed.length === 0 && (
              <p className="mt-2 text-xs text-slate-500">Nothing is waiting or running.</p>
            )}
            <ul className="mt-2 space-y-1.5 text-xs">
              {[...active, ...failed].slice(0, 8).map((p, i) => (
                <li key={`${p.case_id}-${p.file}-${i}`} className="flex items-center justify-between gap-2">
                  <Link href={`/cases/${p.case_id}/evidence`} className="min-w-0 truncate text-slate-300 hover:underline" title={`${p.file} · ${p.case_title ?? ""}`}>
                    {p.file}
                  </Link>
                  <Badge tone={p.status === "failed" ? "red" : "blue"}>{p.status}</Badge>
                </li>
              ))}
            </ul>
          </Card>
          <Card className="p-4">
            <p className="text-sm font-medium text-slate-200">Evidence by type</p>
            {s && Object.keys(s.evidence.by_type).length === 0 && <p className="mt-2 text-xs text-slate-500">No evidence yet.</p>}
            <ul className="mt-2 space-y-1.5">
              {s &&
                Object.entries(s.evidence.by_type)
                  .sort((a, b) => b[1] - a[1])
                  .map(([type, n]) => {
                    const max = Math.max(...Object.values(s.evidence.by_type));
                    return (
                      <li key={type} className="text-xs">
                        <div className="flex items-center justify-between text-slate-300">
                          <span className="flex items-center gap-1.5 capitalize">
                            <FileTypeIcon type={type} className="h-3.5 w-3.5 text-slate-500" /> {type}
                          </span>
                          <span className="tabular-nums text-slate-400">{n}</span>
                        </div>
                        <div className="mt-0.5 h-1 rounded bg-navy-800">
                          <div className="h-1 rounded bg-gradient-to-r from-sky-500 to-indigo-400" style={{ width: `${(n / max) * 100}%` }} />
                        </div>
                      </li>
                    );
                  })}
            </ul>
          </Card>
          <Card className="p-4 text-xs text-slate-500">
            <p className="flex items-center gap-1.5 font-medium text-slate-300">
              <Waypoints className="h-4 w-4 text-sky-300" aria-hidden /> How a case flows
            </p>
            <ol className="mt-2 list-decimal space-y-1 pl-4">
              <li>Upload evidence; every file is validated by its content.</li>
              <li>Process it: text, OCR, transcripts and video frames keep their exact location.</li>
              <li>Run the analysis: claims, entities and event proposals.</li>
              <li>Review: confirm events, decide on possible inconsistencies.</li>
              <li>Generate a versioned report.</li>
            </ol>
          </Card>
        </aside>
      </div>
    </div>
  );
}

function Metric({
  icon,
  label,
  value,
  hint,
  amber = false,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | undefined;
  hint?: string;
  amber?: boolean;
}) {
  return (
    <div className="rounded-xl border border-white/[0.06] bg-navy-950/50 px-4 py-3 backdrop-blur">
      <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-slate-500">
        {icon}
        {label}
      </p>
      {value === undefined ? (
        <div className="evx-skeleton mt-2 h-7 w-12 rounded" />
      ) : (
        <p className={clsx("mt-1 text-2xl font-semibold tabular-nums", amber ? "text-inconsistency" : "text-slate-50")}>{value}</p>
      )}
      {hint && <p className="text-xs text-slate-500">{hint}</p>}
    </div>
  );
}
