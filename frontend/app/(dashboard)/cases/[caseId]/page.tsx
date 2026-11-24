"use client";

import Link from "next/link";
import { AlertTriangle, ArrowRight } from "lucide-react";
import { getDashboard } from "@/lib/api/analysis";
import { formatBytes, formatDateTime } from "@/lib/format";
import { useCaseContext } from "@/components/cases/case-shell";
import { actionLabel, methodLabel } from "@/components/analysis/review-labels";
import { countHint, countTone, countValue } from "@/components/analysis/analysis-state";
import {
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  SectionHeader,
  StatTile,
} from "@/components/ui/primitives";
import { useApi } from "@/hooks/use-api";

function Breakdown({ title, values }: { title: string; values: Record<string, number> }) {
  const entries = Object.entries(values).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  return (
    <div>
      <p className="text-xs font-medium text-slate-400">{title}</p>
      {entries.length === 0 ? (
        <p className="mt-1 text-xs text-slate-600">None yet</p>
      ) : (
        <ul className="mt-1.5 space-y-1">
          {entries.map(([k, v]) => (
            <li key={k} className="text-xs">
              <div className="flex justify-between text-slate-300">
                <span>{k.replace(/_/g, " ")}</span>
                <span className="tabular-nums text-slate-400">{v}</span>
              </div>
              <div className="mt-0.5 h-1 rounded bg-navy-800">
                <div className="h-1 rounded bg-slate-500" style={{ width: `${(v / max) * 100}%` }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function CaseOverviewPage() {
  const { caseItem, analysisVersion, analysisPhase } = useCaseContext();
  const caseId = caseItem.id;
  const { data, error, loading, reload } = useApi(
    (signal) => getDashboard(caseId, signal),
    [caseId, analysisVersion],
    "Could not load the case overview.",
  );

  if (loading && !data) return <LoadingState label="Loading overview…" />;
  if (error && !data) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  const openConflicts =
    (data.contradictions.by_status.unreviewed ?? 0) + (data.contradictions.by_status.unresolved ?? 0);
  const failed = data.evidence.by_status.failed ?? 0;
  const completed = data.evidence.by_status.completed ?? 0;
  const root = `/cases/${caseId}`;

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Overview"
        description={
          <>
            Figures below come from this case&apos;s stored records. Claims are produced by{" "}
            <span className="text-slate-300">{methodLabel(data.claim_method)}</span>; every claim
            quotes its source and stays unverified until a person reviews it.
          </>
        }
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        <StatTile
          label="Evidence"
          value={data.evidence.total}
          hint={`${completed} processed${failed ? ` · ${failed} failed` : ""} · ${formatBytes(data.evidence.bytes)}`}
          tone={failed ? "red" : completed === data.evidence.total && completed > 0 ? "green" : "neutral"}
        />
        <StatTile label="Segments" value={data.segments} hint="extracted, current runs" />
        <StatTile label="Claims" value={data.claims.total} hint={`${data.claims.by_status.verified ?? 0} verified`} />
        <StatTile label="Entities" value={data.entities.total} hint={`${data.entities.candidates} possible duplicates`} />
        <StatTile
          label="Potential inconsistencies"
          value={countValue(data.contradictions.total, analysisPhase)}
          hint={
            analysisPhase === "completed" || analysisPhase === "running"
              ? `${openConflicts} awaiting review`
              : countHint(openConflicts, analysisPhase)
          }
          tone={countTone(openConflicts, analysisPhase)}
        />
        <StatTile
          label="Review queue"
          value={countValue(data.review_queue, analysisPhase)}
          hint={countHint(data.review_queue, analysisPhase)}
          tone={countTone(data.review_queue, analysisPhase)}
        />
      </div>

      {data.evidence.total === 0 && (
        <EmptyState title="No evidence yet">
          Upload files in the <Link className="underline" href={`${root}/evidence`}>Evidence</Link>{" "}
          section, process them, then run the analysis.
        </EmptyState>
      )}

      {data.evidence.total > 0 && !data.latest_run && (
        <Card className="p-4">
          <p className="text-sm text-slate-300">
            This case has not been analysed yet. Process the evidence, then use{" "}
            <span className="font-medium text-slate-100">Run analysis</span> above to extract
            claims, entities and potential inconsistencies.
          </p>
        </Card>
      )}

      {openConflicts > 0 && (
        <Link
          href={`${root}/contradictions`}
          className="flex items-center justify-between rounded-lg border border-inconsistency/30 bg-inconsistency/5 px-4 py-3 text-sm text-inconsistency hover:bg-inconsistency/10"
        >
          <span className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4" aria-hidden />
            {openConflicts} potential inconsistenc{openConflicts === 1 ? "y" : "ies"} between
            sources await human review
          </span>
          <ArrowRight className="h-4 w-4" aria-hidden />
        </Link>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="space-y-4 p-4">
          <Breakdown title="Evidence by type" values={data.evidence.by_type} />
          <Breakdown title="Evidence by processing status" values={data.evidence.by_status} />
        </Card>
        <Card className="space-y-4 p-4">
          <Breakdown title="Claims by review status" values={data.claims.by_status} />
          <Breakdown title="Claims by source modality" values={data.claims.by_modality} />
        </Card>
        <Card className="space-y-4 p-4">
          <Breakdown title="Entities by type" values={data.entities.by_type} />
          <Breakdown title="Potential inconsistencies by status" values={data.contradictions.by_status} />
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <p className="text-sm font-medium text-slate-200">Entities seen in the most evidence</p>
          {data.top_entities.length === 0 ? (
            <p className="mt-2 text-xs text-slate-500">No entities yet.</p>
          ) : (
            <ul className="mt-2 divide-y divide-navy-800">
              {data.top_entities.map((e) => (
                <li key={e.id} className="flex items-center justify-between py-1.5 text-sm">
                  <Link href={`${root}/entities?focus=${e.id}`} className="truncate text-slate-200 hover:underline">
                    {e.display_name}
                    <span className="ml-2 text-xs text-slate-500">{e.entity_type}</span>
                  </Link>
                  <span className="text-xs tabular-nums text-slate-400">
                    {e.evidence_count} file{e.evidence_count === 1 ? "" : "s"} · {e.mention_count} mention
                    {e.mention_count === 1 ? "" : "s"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card className="p-4">
          <p className="text-sm font-medium text-slate-200">Recent review activity</p>
          {data.recent_activity.length === 0 ? (
            <p className="mt-2 text-xs text-slate-500">No review decisions recorded yet.</p>
          ) : (
            <ul className="mt-2 space-y-1.5">
              {data.recent_activity.map((a) => (
                <li key={a.id} className="text-xs text-slate-400">
                  <span className="text-slate-200">{actionLabel(a.action)}</span> on {a.target_type}
                  {a.to_status && a.from_status !== a.to_status ? ` → ${a.to_status}` : ""} ·{" "}
                  {a.reviewer ?? "unspecified"} · {formatDateTime(a.created_at)}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {data.latest_run && (
        <p className="text-xs text-slate-500">
          Latest analysis: {data.latest_run.status} · started {formatDateTime(data.latest_run.started_at)}
          {typeof data.latest_run.stats.claims_created === "number" &&
            ` · ${data.latest_run.stats.claims_created} new claims`}
          {typeof data.latest_run.stats.contradictions_created === "number" &&
            ` · ${data.latest_run.stats.contradictions_created} new potential inconsistencies`}
        </p>
      )}
    </div>
  );
}
