"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { listClaims } from "@/lib/api/analysis";
import type { Claim } from "@/lib/types/analysis";
import { useCaseContext } from "@/components/cases/case-shell";
import { ClaimCard } from "@/components/analysis/claim-card";
import { AnalysisEmptyState, AnalysisPhaseNotice } from "@/components/analysis/analysis-empty";
import {
  BUTTON,
  ErrorState,
  INPUT,
  LoadingState,
  SectionHeader,
} from "@/components/ui/primitives";
import { useApi } from "@/hooks/use-api";

const PAGE = 25;
const SELECT = `${INPUT} w-auto py-1 text-xs`;

export default function ClaimsPage() {
  const { caseItem, analysisVersion } = useCaseContext();
  const caseId = caseItem.id;
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");
  const [modality, setModality] = useState("");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [superseded, setSuperseded] = useState(false);
  const [offset, setOffset] = useState(0);

  const { data, error, loading, reload, setData } = useApi(
    (signal) =>
      listClaims(
        caseId,
        {
          reviewStatus: status || undefined,
          claimType: type || undefined,
          modality: modality || undefined,
          q: q || undefined,
          includeSuperseded: superseded,
          limit: PAGE,
          offset,
        },
        signal,
      ),
    [caseId, status, type, modality, q, superseded, offset, analysisVersion],
    "Could not load claims.",
  );

  function replace(updated: Claim) {
    if (!data) return;
    setData({ ...data, items: data.items.map((c) => (c.id === updated.id ? { ...c, ...updated } : c)) });
  }

  const reset = (fn: () => void) => {
    fn();
    setOffset(0);
  };

  return (
    <div>
      <SectionHeader
        title="Claims"
        description="Statements found in the evidence, each with its exact source quote. A claim records what a source says; it is not established as true until a reviewer verifies it."
      />

      <form
        className="mb-4 flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          reset(() => setQ(search.trim()));
        }}
      >
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-2 h-3.5 w-3.5 text-slate-500" aria-hidden />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search claim text or quote"
            className={`${INPUT} w-64 py-1 pl-7 text-xs`}
            aria-label="Search claims"
          />
        </div>
        <select value={status} onChange={(e) => reset(() => setStatus(e.target.value))} className={SELECT} aria-label="Review status">
          <option value="">All review states</option>
          <option value="unreviewed">Unreviewed</option>
          <option value="needs_verification">Needs verification</option>
          <option value="verified">Verified</option>
          <option value="rejected">Rejected</option>
        </select>
        <select value={type} onChange={(e) => reset(() => setType(e.target.value))} className={SELECT} aria-label="Claim type">
          <option value="">All types</option>
          <option value="date_time">Date / time</option>
          <option value="quantity">Quantity</option>
          <option value="location">Location</option>
          <option value="identity">Identity</option>
          <option value="record">Record</option>
          <option value="statement">Statement</option>
        </select>
        <select value={modality} onChange={(e) => reset(() => setModality(e.target.value))} className={SELECT} aria-label="Source modality">
          <option value="">All sources</option>
          <option value="pdf">PDF</option>
          <option value="image">Image (OCR)</option>
          <option value="audio">Audio (transcript)</option>
          <option value="tabular">Table</option>
          <option value="email">Email</option>
        </select>
        <label className="flex items-center gap-1.5 text-xs text-slate-400">
          <input type="checkbox" checked={superseded} onChange={(e) => reset(() => setSuperseded(e.target.checked))} />
          Include claims from earlier runs
        </label>
        <button type="submit" className={BUTTON}>
          Apply
        </button>
      </form>

      {loading && !data && <LoadingState label="Loading claims…" />}
      {error && <ErrorState message={error} onRetry={reload} />}
      {data && data.total > 0 && <AnalysisPhaseNotice />}
      {data && data.total === 0 && (
        <AnalysisEmptyState
          kind="claims"
          filtered={Boolean(status || type || modality || q)}
        />
      )}
      {data && data.items.length > 0 && (
        <>
          <p className="mb-2 text-xs text-slate-500">
            {data.total} claim{data.total === 1 ? "" : "s"}
          </p>
          <div className="space-y-3">
            {data.items.map((c) => (
              <ClaimCard key={c.id} caseId={caseId} claim={c} showEvidence onChanged={replace} />
            ))}
          </div>
          {data.total > PAGE && (
            <div className="mt-4 flex items-center justify-between text-xs text-slate-400">
              <button type="button" className={BUTTON} disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                <ChevronLeft className="h-3.5 w-3.5" aria-hidden /> Previous
              </button>
              <span>
                {offset + 1}–{Math.min(offset + data.items.length, data.total)} of {data.total}
              </span>
              <button type="button" className={BUTTON} disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>
                Next <ChevronRight className="h-3.5 w-3.5" aria-hidden />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
