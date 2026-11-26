"use client";

import { useEffect, useState } from "react";
import { Loader2, Waypoints, Wand2 } from "lucide-react";
import { listEvents, proposeEvents } from "@/lib/api/phase2";
import { hasRole } from "@/lib/types/case";
import { useCaseContext } from "@/components/cases/case-shell";
import { EventCard } from "@/components/events/event-card";
import { AnalysisPhaseNotice } from "@/components/analysis/analysis-empty";
import {
  BUTTON,
  EmptyState,
  ErrorState,
  SectionHeader,
  Skeleton,
  StatTile,
  Tabs,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { errorText, useApi } from "@/hooks/use-api";

type Filter = "all" | "proposed" | "confirmed" | "rejected";

export default function EventsPage() {
  const { caseItem, role, analysisVersion } = useCaseContext();
  const caseId = caseItem.id;
  const notify = useToast();
  const [filter, setFilter] = useState<Filter>("proposed");
  const [version, setVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const all = useApi((signal) => listEvents(caseId, {}, signal), [caseId, analysisVersion, version], "Could not load events.");

  const items = all.data?.items ?? [];
  const count = (s: Filter) => (s === "all" ? items.length : items.filter((e) => e.status === s).length);

  // Open on "Proposed" only while something awaits review; otherwise a case whose
  // events were all decided would look empty on arrival.
  const [chosen, setChosen] = useState(false);
  useEffect(() => {
    if (!chosen && all.data) setFilter(all.data.items.some((e) => e.status === "proposed") ? "proposed" : "all");
  }, [all.data, chosen]);
  const shown = filter === "all" ? items : items.filter((e) => e.status === filter);

  async function repropose() {
    setBusy(true);
    try {
      const res = await proposeEvents(caseId);
      notify(res.created ? "success" : "info", res.created ? `${res.created} new proposal(s)` : "No new proposals", "Existing decisions were kept.");
      setVersion((n) => n + 1);
    } catch (err) {
      notify("error", "Proposals could not be refreshed", errorText(err, ""));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <SectionHeader
        title="Events"
        description="Claims that may describe the same real-world occurrence, grouped by shared identifiers, plates, places or object words. A grouping is only a proposal: accounts are compared for possible inconsistencies after a reviewer confirms it."
        actions={
          hasRole(role, "editor") ? (
            <button type="button" className={BUTTON} onClick={() => void repropose()} disabled={busy}>
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Wand2 className="h-3.5 w-3.5" aria-hidden />}
              Re-run proposals
            </button>
          ) : undefined
        }
      />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Proposed" value={count("proposed")} hint="awaiting a reviewer" />
        <StatTile label="Confirmed" value={count("confirmed")} hint="accounts compared" tone={count("confirmed") ? "green" : "neutral"} />
        <StatTile label="Rejected" value={count("rejected")} hint="not one occurrence" />
        <StatTile
          label="Pairs that differ"
          value={items.reduce((n, e) => n + e.comparisons.filter((c) => c.is_candidate).length, 0)}
          hint="across all events"
          tone="amber"
        />
      </div>
      <Tabs<Filter>
        label="Event status"
        active={filter}
        onChange={(f) => {
          setChosen(true);
          setFilter(f);
        }}
        tabs={(["proposed", "confirmed", "rejected", "all"] as Filter[]).map((id) => ({
          id,
          label: id[0].toUpperCase() + id.slice(1),
          count: count(id),
        }))}
      />
      <div className="mt-4 space-y-3">
        {all.loading && !all.data && <Skeleton rows={3} />}
        {all.error && <ErrorState message={all.error} onRetry={all.reload} />}
        {all.data && items.length > 0 && <AnalysisPhaseNotice />}
        {all.data && shown.length === 0 && (
          <EmptyState title={items.length ? `No ${filter} events` : "No events proposed"} icon={<Waypoints className="h-5 w-5" aria-hidden />}>
            {items.length
              ? "Choose another filter above."
              : "Events need at least two accounts of the same kind of occurrence that share an anchor. Process evidence and run the analysis."}
          </EmptyState>
        )}
        {shown.map((e, i) => (
          <EventCard
            key={e.id}
            caseId={caseId}
            event={e}
            role={role}
            defaultOpen={i === 0}
            onChanged={() => setVersion((n) => n + 1)}
          />
        ))}
      </div>
    </div>
  );
}
