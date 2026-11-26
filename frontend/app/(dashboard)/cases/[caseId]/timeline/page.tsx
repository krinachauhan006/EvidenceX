"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import clsx from "clsx";
import { AlertTriangle, CalendarClock, Link2 } from "lucide-react";
import { getTimeline } from "@/lib/api/phase2";
import { listEvidence } from "@/lib/api/evidence";
import type { TimelineItem } from "@/lib/types/phase2";
import { useCaseContext } from "@/components/cases/case-shell";
import { sourceHref } from "@/components/analysis/source-link";
import { sourceLabel } from "@/components/analysis/claim-card";
import { claimStatus } from "@/components/analysis/review-labels";
import { hhmm } from "@/components/events/event-labels";
import { AnalysisPhaseNotice } from "@/components/analysis/analysis-empty";
import {
  Badge,
  BUTTON,
  Card,
  EmptyState,
  ErrorState,
  INPUT,
  SectionHeader,
  Skeleton,
} from "@/components/ui/primitives";
import { useApi } from "@/hooks/use-api";

const SELECT = `${INPUT} w-auto py-1 text-xs`;
const MODALITY_COLOUR: Record<string, string> = {
  document: "#93c5fd",
  image: "#a5b4fc",
  audio: "#67e8f9",
  video: "#c4b5fd",
  email: "#cbd5e1",
  tabular: "#86efac",
};
const colourOf = (m: string) => MODALITY_COLOUR[m] ?? "#94a3b8";

export default function TimelinePage() {
  const { caseItem, analysisVersion } = useCaseContext();
  const caseId = caseItem.id;
  const [modality, setModality] = useState("");
  const [reviewStatus, setReviewStatus] = useState("");
  const [evidenceId, setEvidenceId] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const evidence = useApi(() => listEvidence(caseId), [caseId]);
  const tl = useApi(
    (signal) =>
      getTimeline(
        caseId,
        { modality: modality || undefined, reviewStatus: reviewStatus || undefined, evidenceId: evidenceId || undefined },
        signal,
      ),
    [caseId, modality, reviewStatus, evidenceId, analysisVersion],
    "Could not load the timeline.",
  );
  const modalities = useMemo(
    () => Array.from(new Set(tl.data?.groups.flatMap((g) => g.items.map((i) => i.claim.modality)) ?? [])).sort(),
    [tl.data],
  );

  return (
    <div>
      <SectionHeader
        title="Timeline"
        description="Every claim with a time or date, in chronological order per stated day. Dates keep their precision: a date inherited from the document is marked, and claims without a date are listed separately instead of being placed on a day."
        actions={
          <>
            <select className={SELECT} value={modality} onChange={(e) => setModality(e.target.value)} aria-label="Modality">
              <option value="">All sources</option>
              {["document", "image", "audio", "video", "email", "tabular"].map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
            <select className={SELECT} value={reviewStatus} onChange={(e) => setReviewStatus(e.target.value)} aria-label="Review status">
              <option value="">Any review status</option>
              <option value="unreviewed">Unreviewed</option>
              <option value="verified">Verified</option>
              <option value="needs_verification">Needs verification</option>
              <option value="rejected">Rejected</option>
            </select>
            <select className={`${SELECT} max-w-[14rem]`} value={evidenceId} onChange={(e) => setEvidenceId(e.target.value)} aria-label="Evidence item">
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
      {tl.loading && !tl.data && <Skeleton rows={4} />}
      {tl.error && <ErrorState message={tl.error} onRetry={tl.reload} />}
      {tl.data && tl.data.total > 0 && <AnalysisPhaseNotice />}
      {tl.data && tl.data.total === 0 && (
        <EmptyState title="Nothing to place on the timeline" icon={<CalendarClock className="h-5 w-5" aria-hidden />}>
          Claims with a time or date appear here after the analysis. Try clearing the filters.
        </EmptyState>
      )}
      {modalities.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-3 text-[11px] text-slate-400" aria-label="Legend">
          {modalities.map((m) => (
            <span key={m} className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: colourOf(m) }} aria-hidden /> {m}
            </span>
          ))}
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full ring-2 ring-inconsistency" aria-hidden /> in a possible inconsistency
          </span>
        </div>
      )}
      <div className="space-y-5">
        {tl.data?.groups.map((g) => (
          <DayLane
            key={g.date ?? "undated"}
            caseId={caseId}
            date={g.date}
            items={g.items}
            note={tl.data!.undated_note}
            selected={selected}
            onSelect={setSelected}
          />
        ))}
      </div>
    </div>
  );
}

function DayLane({
  caseId,
  date,
  items,
  note,
  selected,
  onSelect,
}: {
  caseId: string;
  date: string | null;
  items: TimelineItem[];
  note: string;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const timed = items.filter((i) => i.start_minute !== null);
  const lo = timed.length ? Math.max(0, Math.min(...timed.map((i) => i.start_minute!)) - 30) : 0;
  const hi = timed.length ? Math.min(1440, Math.max(...timed.map((i) => i.end_minute ?? i.start_minute!)) + 30) : 1440;
  const span = Math.max(60, hi - lo);
  const pos = (m: number) => `${((m - lo) / span) * 100}%`;
  const label = date
    ? new Date(`${date}T00:00:00Z`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "long", year: "numeric", timeZone: "UTC" })
    : "Date not stated";

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-100">{label}</h3>
        <span className="text-xs text-slate-500">
          {items.length} claim{items.length === 1 ? "" : "s"}
        </span>
      </div>
      {!date && <p className="mt-1 text-xs text-slate-500">{note}</p>}
      {timed.length > 0 && (
        <div className="mt-3">
          <div className="relative h-12 rounded-lg border border-navy-800 bg-navy-950/70">
            <div className="absolute inset-x-2 top-1/2 h-px bg-navy-700" />
            {timed.map((i) => {
              const a = i.start_minute!;
              const b = i.end_minute ?? a;
              const conflict = i.contradiction_ids.length > 0;
              return (
                <button
                  key={i.claim.id}
                  type="button"
                  onClick={() => onSelect(i.claim.id)}
                  title={`${i.time_raw ?? hhmm(a)} · ${i.claim.evidence_name}`}
                  aria-label={`${i.time_raw ?? hhmm(a)} in ${i.claim.evidence_name}`}
                  className={clsx(
                    "absolute top-1/2 -translate-y-1/2 rounded-full border-2 transition-transform hover:scale-125 focus-visible:scale-125",
                    conflict ? "border-inconsistency" : "border-navy-950",
                    selected === i.claim.id && "scale-125 ring-2 ring-sky-400",
                  )}
                  style={{
                    left: pos(a),
                    width: b > a ? `calc(${pos(b)} - ${pos(a)})` : "14px",
                    marginLeft: b > a ? 0 : "-7px",
                    height: "14px",
                    background: colourOf(i.claim.modality),
                  }}
                />
              );
            })}
          </div>
          <div className="mt-0.5 flex justify-between text-[10px] tabular-nums text-slate-600">
            <span>{hhmm(lo)}</span>
            <span>{hhmm(lo + span)}</span>
          </div>
        </div>
      )}
      <ol className="mt-3 space-y-1.5">
        {items.map((i) => {
          const st = claimStatus(i.claim.review_status);
          return (
            <li
              key={i.claim.id}
              className={clsx(
                "grid gap-2 rounded-lg border p-2.5 text-sm transition-colors md:grid-cols-[6rem_minmax(0,1fr)_auto]",
                selected === i.claim.id ? "border-sky-500/50 bg-sky-500/5" : "border-navy-800 bg-navy-950/40 hover:border-navy-600",
              )}
              onClick={() => onSelect(i.claim.id)}
            >
              <div className="text-xs">
                <span className="font-mono text-slate-100">{i.time_raw ?? (i.start_minute !== null ? hhmm(i.start_minute) : "—")}</span>
                <span className="block text-[11px] text-slate-500">
                  {i.time_precision ?? "no time"}
                  {i.tz ? ` · ${i.tz}` : ""}
                </span>
              </div>
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
                  <span className="h-2 w-2 rounded-full" style={{ background: colourOf(i.claim.modality) }} aria-hidden />
                  {i.claim.evidence_name} · {sourceLabel(i.claim.locator)}
                  {i.date_precision === "inherited_day" && <Badge title="The date comes from elsewhere in the same document">date inherited</Badge>}
                  {i.date_source === "email_header" && <Badge>date from email header</Badge>}
                </p>
                <p className="mt-0.5 break-words font-mono text-[13px] text-slate-200">{i.claim.quote}</p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {i.events.map((e) => (
                    <Link key={e.id} href={`/cases/${caseId}/events`} className="rounded-full border border-sky-500/30 px-2 py-0.5 text-[11px] text-sky-300 hover:bg-sky-500/10">
                      {e.title} · {e.status}
                    </Link>
                  ))}
                  {i.contradiction_ids.length > 0 && (
                    <Link href={`/cases/${caseId}/contradictions`} className="inline-flex items-center gap-1 rounded-full border border-inconsistency/40 px-2 py-0.5 text-[11px] text-inconsistency hover:bg-inconsistency/10">
                      <AlertTriangle className="h-3 w-3" aria-hidden /> possible inconsistency
                    </Link>
                  )}
                </div>
              </div>
              <div className="flex items-start gap-1.5">
                <Badge tone={st.tone}>{st.label}</Badge>
                {i.claim.segment_id && (
                  <Link
                    className={BUTTON}
                    href={sourceHref(caseId, {
                      evidenceId: i.claim.evidence_id,
                      segmentId: i.claim.segment_id,
                      claimId: i.claim.id,
                      locator: i.claim.locator,
                    })}
                    aria-label="Open source"
                  >
                    <Link2 className="h-3 w-3" aria-hidden />
                  </Link>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
