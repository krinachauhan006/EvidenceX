"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Plus, Inbox } from "lucide-react";
import { listCases } from "@/lib/api/cases";
import type { Case, CaseStatus } from "@/lib/types/case";
import { CaseForm } from "@/components/cases/case-form";
import { StatusBadge } from "@/components/ui/status-badge";

const PAGE_SIZE = 20;

export default function CasesPage() {
  const [cases, setCases] = useState<Case[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [statusFilter, setStatusFilter] = useState<CaseStatus | "all">("open");
  const [showForm, setShowForm] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
      setError("Could not reach the API. Is the backend running on :8000?");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div>
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-100">
            Cases
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            Each case is a container for evidence and findings.
          </p>
        </div>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="inline-flex items-center gap-2 rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-slate-100 hover:bg-navy-600"
        >
          <Plus className="h-4 w-4" aria-hidden />
          New case
        </button>
      </header>

      {showForm && (
        <section className="mb-6 rounded-lg border border-navy-800 bg-navy-900 p-5">
          <h2 className="mb-4 text-sm font-medium text-slate-200">
            Create a new case
          </h2>
          <CaseForm
            onDone={() => {
              setShowForm(false);
              setOffset(0);
              void load();
            }}
          />
        </section>
      )}

      <div className="mb-4 flex gap-2 text-sm">
        {(["open", "archived", "all"] as const).map((s) => (
          <button
            key={s}
            onClick={() => {
              setStatusFilter(s);
              setOffset(0);
            }}
            className={
              statusFilter === s
                ? "rounded-md bg-navy-700 px-3 py-1 text-slate-100"
                : "rounded-md px-3 py-1 text-slate-400 hover:text-slate-200"
            }
          >
            {s}
          </button>
        ))}
      </div>

      {error && (
        <p role="alert" className="rounded-md bg-charcoal-800 p-4 text-sm text-inconsistency">
          {error}
        </p>
      )}

      {!error && loading && <p className="text-sm text-slate-500">Loading…</p>}

      {!error && !loading && cases.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-navy-800 py-16 text-center">
          <Inbox className="h-8 w-8 text-slate-600" aria-hidden />
          <p className="text-sm text-slate-400">No cases yet.</p>
        </div>
      )}

      {!error && !loading && cases.length > 0 && (
        <ul className="divide-y divide-navy-800 overflow-hidden rounded-lg border border-navy-800 bg-navy-900">
          {cases.map((c) => (
            <li key={c.id}>
              <Link
                href={`/cases/${c.id}`}
                className="flex items-center justify-between px-5 py-4 hover:bg-navy-850"
              >
                <div className="min-w-0">
                  <p className="truncate font-medium text-slate-100">{c.title}</p>
                  {c.description && (
                    <p className="mt-0.5 truncate text-sm text-slate-500">
                      {c.description}
                    </p>
                  )}
                </div>
                <StatusBadge status={c.status} />
              </Link>
            </li>
          ))}
        </ul>
      )}

      {!error && total > PAGE_SIZE && (
        <div className="mt-4 flex items-center justify-between text-sm text-slate-400">
          <button
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
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset((o) => o + PAGE_SIZE)}
            className="rounded-md px-3 py-1 hover:text-slate-200 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
