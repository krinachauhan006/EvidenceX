"use client";

import { useState } from "react";
import { getGraph } from "@/lib/api/analysis";
import { listEvidence } from "@/lib/api/evidence";
import { useCaseContext } from "@/components/cases/case-shell";
import { KnowledgeGraph } from "@/components/analysis/knowledge-graph";
import { AnalysisEmptyState, AnalysisPhaseNotice } from "@/components/analysis/analysis-empty";
import {
  ErrorState,
  INPUT,
  LoadingState,
  SectionHeader,
} from "@/components/ui/primitives";
import { useApi } from "@/hooks/use-api";

const SELECT = `${INPUT} w-auto py-1 text-xs`;

export default function GraphPage() {
  const { caseItem, analysisVersion } = useCaseContext();
  const caseId = caseItem.id;
  const [includeClaims, setIncludeClaims] = useState(true);
  const [conflictsOnly, setConflictsOnly] = useState(false);
  const [entityType, setEntityType] = useState("");
  const [evidenceId, setEvidenceId] = useState("");

  const evidence = useApi(() => listEvidence(caseId), [caseId]);
  const { data, error, loading, reload } = useApi(
    (signal) =>
      getGraph(
        caseId,
        {
          includeClaims,
          contradictionsOnly: conflictsOnly,
          entityType: entityType || undefined,
          evidenceId: evidenceId || undefined,
          limit: 250,
        },
        signal,
      ),
    [caseId, includeClaims, conflictsOnly, entityType, evidenceId, analysisVersion],
    "Could not load the graph.",
  );

  return (
    <div>
      <SectionHeader
        title="Knowledge graph"
        description="Evidence items, the claims extracted from them, the entities those claims mention, and potential inconsistencies between them. Every link comes from stored records."
        actions={
          <>
            <label className="flex items-center gap-1.5 text-xs text-slate-400">
              <input type="checkbox" checked={includeClaims} onChange={(e) => setIncludeClaims(e.target.checked)} />
              Show claims
            </label>
            <label className="flex items-center gap-1.5 text-xs text-slate-400">
              <input type="checkbox" checked={conflictsOnly} onChange={(e) => setConflictsOnly(e.target.checked)} />
              Only claims in potential inconsistencies
            </label>
            <select value={entityType} onChange={(e) => setEntityType(e.target.value)} className={SELECT} aria-label="Entity type">
              <option value="">All entity types</option>
              <option value="shipment">Shipment</option>
              <option value="identifier">Identifier</option>
              <option value="vehicle">Vehicle</option>
              <option value="location">Location</option>
              <option value="contact">Contact</option>
            </select>
            <select value={evidenceId} onChange={(e) => setEvidenceId(e.target.value)} className={`${SELECT} max-w-[14rem]`} aria-label="Evidence item">
              <option value="">All evidence</option>
              {evidence.data?.items.map((ev) => (
                <option key={ev.id} value={ev.id}>
                  {ev.original_filename}
                </option>
              ))}
            </select>
          </>
        }
      />
      {loading && !data && <LoadingState label="Building graph…" />}
      {error && <ErrorState message={error} onRetry={reload} />}
      {data && data.nodes.length === 0 && (
        <AnalysisEmptyState kind="graph" filtered={Boolean(entityType || evidenceId || conflictsOnly)} />
      )}
      {data && data.nodes.length > 0 && <AnalysisPhaseNotice />}
      {data && data.nodes.length > 0 && <KnowledgeGraph caseId={caseId} graph={data} />}
    </div>
  );
}
