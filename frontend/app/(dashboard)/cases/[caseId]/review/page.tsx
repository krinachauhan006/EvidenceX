"use client";

import Link from "next/link";
import { reviewQueue } from "@/lib/api/analysis";
import type { Claim, Contradiction } from "@/lib/types/analysis";
import { useCaseContext } from "@/components/cases/case-shell";
import { ClaimCard } from "@/components/analysis/claim-card";
import { ContradictionCard } from "@/components/analysis/contradiction-card";
import { AnalysisEmptyState, AnalysisPhaseNotice } from "@/components/analysis/analysis-empty";
import { countHint, countTone, countValue } from "@/components/analysis/analysis-state";
import {
  Card,
  ErrorState,
  LoadingState,
  SectionHeader,
  StatTile,
} from "@/components/ui/primitives";
import { useApi } from "@/hooks/use-api";

export default function ReviewQueuePage() {
  const { caseItem, analysisVersion, analysisPhase } = useCaseContext();
  const caseId = caseItem.id;
  const { data, error, loading, reload, setData } = useApi(
    (signal) => reviewQueue(caseId, signal),
    [caseId, analysisVersion],
    "Could not load the review queue.",
  );

  if (loading && !data) return <LoadingState label="Loading review queue…" />;
  if (error && !data) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  const claimChanged = (c: Claim) =>
    setData({ ...data, claims: data.claims.map((x) => (x.id === c.id ? { ...x, ...c } : x)) });
  const conflictChanged = (c: Contradiction) =>
    setData({ ...data, contradictions: data.contradictions.map((x) => (x.id === c.id ? c : x)) });

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Review queue"
        description="Everything waiting for a human decision, most important first: potential inconsistencies, then claims that take part in them, need verification, or come from machine transcription or OCR. Each decision is recorded in the audit history."
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {(
          [
            ["Waiting in total", data.counts.total ?? 0],
            ["Potential inconsistencies", data.counts.contradictions ?? 0],
            ["Claims", data.counts.claims ?? 0],
            ["Possible duplicate entities", data.counts.candidates ?? 0],
          ] as const
        ).map(([label, count]) => (
          <StatTile
            key={label}
            label={label}
            value={countValue(count, analysisPhase)}
            hint={countHint(count, analysisPhase)}
            tone={countTone(count, analysisPhase)}
          />
        ))}
      </div>

      {(data.counts.total ?? 0) > 0 && <AnalysisPhaseNotice />}
      {(data.counts.total ?? 0) === 0 && <AnalysisEmptyState kind="review" />}

      {data.contradictions.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-medium text-slate-200">Potential inconsistencies</h3>
          <div className="space-y-3">
            {data.contradictions.map((c) => (
              <ContradictionCard key={c.id} caseId={caseId} item={c} onChanged={conflictChanged} />
            ))}
          </div>
        </section>
      )}

      {data.candidates.length > 0 && (
        <Card className="p-4">
          <h3 className="text-sm font-medium text-slate-200">Possible duplicate entities</h3>
          <ul className="mt-2 space-y-1 text-sm">
            {data.candidates.slice(0, 10).map((c) => (
              <li key={`${c.entity_a.id}-${c.entity_b.id}`} className="text-slate-300">
                {c.entity_a.display_name} / {c.entity_b.display_name}{" "}
                <span className="text-xs text-inconsistency/90">({c.reason})</span>
              </li>
            ))}
          </ul>
          <Link href={`/cases/${caseId}/entities`} className="mt-2 inline-block text-xs text-slate-400 underline">
            Decide in Entities
          </Link>
        </Card>
      )}

      {data.claims.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-medium text-slate-200">
            Claims to review (showing {data.claims.length} of {data.counts.claims})
          </h3>
          <div className="space-y-3">
            {data.claims.map((c) => (
              <ClaimCard key={c.id} caseId={caseId} claim={c} showEvidence onChanged={claimChanged} compact />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
