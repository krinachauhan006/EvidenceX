"use client";

import { useState } from "react";
import { listContradictions } from "@/lib/api/analysis";
import type { Contradiction } from "@/lib/types/analysis";
import { useCaseContext } from "@/components/cases/case-shell";
import { ContradictionCard } from "@/components/analysis/contradiction-card";
import { AnalysisEmptyState, AnalysisPhaseNotice } from "@/components/analysis/analysis-empty";
import {
  ErrorState,
  INPUT,
  LoadingState,
  SectionHeader,
} from "@/components/ui/primitives";
import { useApi } from "@/hooks/use-api";

const SELECT = `${INPUT} w-auto py-1 text-xs`;

export default function ContradictionsPage() {
  const { caseItem, analysisVersion } = useCaseContext();
  const caseId = caseItem.id;
  const [status, setStatus] = useState("");
  const [severity, setSeverity] = useState("");
  const { data, error, loading, reload, setData } = useApi(
    (signal) =>
      listContradictions(
        caseId,
        { reviewStatus: status || undefined, severity: severity || undefined },
        signal,
      ),
    [caseId, status, severity, analysisVersion],
    "Could not load potential inconsistencies.",
  );

  function replace(updated: Contradiction) {
    if (!data) return;
    setData({ ...data, items: data.items.map((c) => (c.id === updated.id ? updated : c)) });
  }

  return (
    <div>
      <SectionHeader
        title="Potential inconsistencies"
        description="Pairs of claims from different evidence items that mention the same identifier and appear to disagree. They are leads for human review: a difference can be benign, and EvidenceX does not decide which source is correct."
        actions={
          <>
            <select value={status} onChange={(e) => setStatus(e.target.value)} className={SELECT} aria-label="Review status">
              <option value="">All states</option>
              <option value="unreviewed">Awaiting review</option>
              <option value="unresolved">Unresolved</option>
              <option value="confirmed">Confirmed</option>
              <option value="rejected">Not an inconsistency</option>
              <option value="resolved">Resolved</option>
            </select>
            <select value={severity} onChange={(e) => setSeverity(e.target.value)} className={SELECT} aria-label="Severity">
              <option value="">All severities</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </>
        }
      />
      {loading && !data && <LoadingState />}
      {error && <ErrorState message={error} onRetry={reload} />}
      {data && data.total > 0 && <AnalysisPhaseNotice />}
      {data && data.total === 0 && (
        <AnalysisEmptyState kind="contradictions" filtered={Boolean(status || severity)} />
      )}
      <div className="space-y-3">
        {data?.items.map((c, i) => (
          <ContradictionCard key={c.id} caseId={caseId} item={c} onChanged={replace} defaultOpen={i === 0} />
        ))}
      </div>
    </div>
  );
}
