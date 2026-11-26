"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Clock, GitMerge, Loader2, Search } from "lucide-react";
import { entityCandidates, getEntity, listEntities, reviewEntity } from "@/lib/api/analysis";
import type { Candidate, CandidateTier, EntityAction, EntityDetail } from "@/lib/types/analysis";
import { hasRole } from "@/lib/types/case";
import { useToast } from "@/components/ui/toast";
import { useCaseContext } from "@/components/cases/case-shell";
import { sourceLabel } from "@/components/analysis/claim-card";
import { HistoryList } from "@/components/analysis/contradiction-card";
import { sourceHref } from "@/components/analysis/source-link";
import { AnalysisEmptyState, AnalysisPhaseNotice } from "@/components/analysis/analysis-empty";
import {
  Badge,
  BUTTON,
  Card,
  EmptyState,
  ErrorState,
  INPUT,
  LoadingState,
  SectionHeader,
} from "@/components/ui/primitives";
import { errorText, useApi } from "@/hooks/use-api";
import { useReviewer } from "@/hooks/use-reviewer";

const RESOLUTION_TONE = {
  unresolved: "neutral",
  confirmed: "green",
  merged: "blue",
  rejected: "red",
} as const;

function EntitiesView() {
  const { caseItem, analysisVersion } = useCaseContext();
  const caseId = caseItem.id;
  const params = useSearchParams();
  const [type, setType] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(params.get("focus"));
  const [version, setVersion] = useState(0);

  const list = useApi(
    (signal) => listEntities(caseId, { entityType: type || undefined, q: search || undefined, includeMerged: true }, signal),
    [caseId, type, search, analysisVersion, version],
    "Could not load entities.",
  );
  const candidates = useApi(
    (signal) => entityCandidates(caseId, signal),
    [caseId, analysisVersion, version],
    "Could not load possible duplicates.",
  );

  useEffect(() => {
    if (!selected && list.data?.items.length) setSelected(list.data.items[0].id);
  }, [list.data, selected]);

  const types = Array.from(new Set(list.data?.items.map((e) => e.entity_type) ?? [])).sort();

  return (
    <div>
      <SectionHeader
        title="Entities"
        description="Identifiers, vehicles, locations and email contacts found in claims. Only identical normalized values share a record (NS-88421 and NS88421). Similar values are listed as possible duplicates and are never merged without a reviewer."
      />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-2 top-2 h-3.5 w-3.5 text-slate-500" aria-hidden />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search names, keys, aliases"
                className={`${INPUT} py-1 pl-7 text-xs`}
                aria-label="Search entities"
              />
            </div>
            <select value={type} onChange={(e) => setType(e.target.value)} className={`${INPUT} w-auto py-1 text-xs`} aria-label="Entity type">
              <option value="">All types</option>
              {types.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          {list.loading && !list.data && <LoadingState />}
          {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
          {list.data && list.data.total > 0 && <AnalysisPhaseNotice />}
          {list.data && list.data.total === 0 && (
            <AnalysisEmptyState kind="entities" filtered={Boolean(type || search.trim())} />
          )}
          {list.data && list.data.items.length > 0 && (
            <Card className="max-h-[32rem] overflow-y-auto">
              <ul className="divide-y divide-navy-800">
                {list.data.items.map((e) => (
                  <li key={e.id}>
                    <button
                      type="button"
                      onClick={() => setSelected(e.id)}
                      aria-pressed={selected === e.id}
                      className={`flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-navy-800/60 ${selected === e.id ? "bg-navy-800" : ""}`}
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-slate-100">{e.display_name}</span>
                        <span className="text-xs text-slate-500">
                          {e.entity_type} · key {e.normalized_key}
                        </span>
                      </span>
                      <span className="flex shrink-0 items-center gap-1.5">
                        {e.resolution_status !== "unresolved" && (
                          <Badge tone={RESOLUTION_TONE[e.resolution_status]}>{e.resolution_status}</Badge>
                        )}
                        <span className="text-xs tabular-nums text-slate-400">
                          {e.evidence_count}f · {e.mention_count}m
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          <CandidatesPanel
            caseId={caseId}
            items={candidates.data?.items ?? []}
            loading={candidates.loading}
            onSelect={setSelected}
            onChanged={() => setVersion((n) => n + 1)}
          />
        </div>
        <div>
          {selected ? (
            <EntityPanel key={selected} caseId={caseId} entityId={selected} version={version} onChanged={() => setVersion((n) => n + 1)} onSelect={setSelected} />
          ) : list.data && list.data.items.length > 0 ? (
            <EmptyState title="Select an entity" />
          ) : null}
        </div>
      </div>
    </div>
  );
}

function CandidatesPanel({
  caseId,
  items,
  loading,
  onSelect,
  onChanged,
}: {
  caseId: string;
  items: Candidate[];
  loading: boolean;
  onSelect: (id: string) => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deferring, setDeferring] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [tier, setTier] = useState<CandidateTier | "all">("all");
  const { role } = useCaseContext();
  const notify = useToast();
  const canReview = hasRole(role, "reviewer");
  const shown = tier === "all" ? items : items.filter((c) => c.tier === tier);

  async function act(c: Candidate, action: EntityAction) {
    setBusy(`${c.entity_a.id}-${action}`);
    setError(null);
    try {
      await reviewEntity(caseId, c.entity_a.id, {
        action,
        target_entity_id: c.entity_b.id,
        note: action === "defer" ? note.trim() : undefined,
      });
      const msg: Record<string, string> = {
        merge: "Merged; the original mentions are kept unchanged",
        mark_distinct: "Marked as different entities",
        defer: "Decision deferred with your note",
      };
      notify("success", msg[action] ?? "Saved");
      setDeferring(null);
      setNote("");
      onChanged();
    } catch (err) {
      const text = errorText(err, "The decision could not be saved.");
      setError(text);
      notify("error", "Not saved", text);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card className="p-3">
      <p className="text-sm font-medium text-slate-200">Possible duplicates ({items.length})</p>
      <p className="text-xs text-slate-500">
        Pairs that may be the same thing, ranked by tier. The score is a heuristic ordering aid, not a
        probability. Decide each pair; nothing is merged automatically.
      </p>
      <div className="mt-2 flex flex-wrap gap-1" role="group" aria-label="Filter by tier">
        {(["all", "exact", "strong", "weak", "conflicting"] as const).map((t) => (
          <button
            key={t}
            type="button"
            aria-pressed={tier === t}
            onClick={() => setTier(t)}
            className={`rounded-full border px-2 py-0.5 text-[11px] ${tier === t ? "border-sky-400/60 bg-sky-500/15 text-sky-200" : "border-navy-700 text-slate-400 hover:text-slate-200"}`}
          >
            {t === "all" ? "All" : TIER[t].label} {t === "all" ? items.length : items.filter((c) => c.tier === t).length}
          </button>
        ))}
      </div>
      {loading && items.length === 0 && <LoadingState />}
      {shown.length === 0 && !loading && <p className="mt-2 text-xs text-slate-500">None.</p>}
      <ul className="mt-2 space-y-2">
        {shown.map((c) => {
          const key = `${c.entity_a.id}-${c.entity_b.id}`;
          const t = TIER[c.tier] ?? TIER.weak;
          return (
            <li key={key} className={`rounded-lg border bg-navy-950/60 p-2.5 text-sm ${t.border}`}>
              <div className="flex flex-wrap items-center gap-1.5 text-slate-200">
                <Badge tone={t.tone} title={t.help}>
                  {t.label} · {Math.round(c.score * 100)}
                </Badge>
                {c.deferred && <Badge title={c.deferred_note ?? undefined}>deferred</Badge>}
                <button type="button" className="hover:underline" onClick={() => onSelect(c.entity_a.id)}>
                  {c.entity_a.display_name}
                </button>
                <span className="text-slate-500">and</span>
                <button type="button" className="hover:underline" onClick={() => onSelect(c.entity_b.id)}>
                  {c.entity_b.display_name}
                </button>
              </div>
              <p className="mt-0.5 text-xs text-slate-400">{c.reason}</p>
              {c.factors.length > 0 && (
                <ul className="mt-1.5 space-y-0.5 text-[11px]">
                  {c.factors.map((f) => (
                    <li key={f.factor} className={f.effect === "+" ? "text-processed/90" : "text-inconsistency/90"}>
                      {f.effect === "+" ? "▲ for" : "▼ against"}: <span className="text-slate-300">{f.factor}</span> · {f.detail}
                    </li>
                  ))}
                </ul>
              )}
              {c.deferred && c.deferred_note && <p className="mt-1 text-[11px] text-slate-500">Deferred: {c.deferred_note}</p>}
              {canReview && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <button type="button" className={BUTTON} disabled={busy !== null} onClick={() => void act(c, "merge")}>
                    {busy === `${c.entity_a.id}-merge` ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> : <GitMerge className="h-3 w-3" aria-hidden />}
                    Same entity: merge
                  </button>
                  <button type="button" className={BUTTON} disabled={busy !== null} onClick={() => void act(c, "mark_distinct")}>
                    Different entities
                  </button>
                  <button type="button" className={BUTTON} disabled={busy !== null} onClick={() => setDeferring(deferring === key ? null : key)} aria-expanded={deferring === key}>
                    <Clock className="h-3 w-3" aria-hidden /> Decide later
                  </button>
                </div>
              )}
              {deferring === key && (
                <div className="mt-2 flex gap-1.5">
                  <input
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="What would settle it?"
                    maxLength={4000}
                    className={`${INPUT} flex-1 py-1 text-xs`}
                    aria-label="Reason for deferring"
                  />
                  <button type="button" className={BUTTON} disabled={busy !== null || !note.trim()} onClick={() => void act(c, "defer")}>
                    Save
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {error && <p role="alert" className="mt-2 text-xs text-failed">{error}</p>}
    </Card>
  );
}

const TIER: Record<CandidateTier, { label: string; tone: "green" | "blue" | "neutral" | "amber"; border: string; help: string }> = {
  exact: { label: "Exact", tone: "green", border: "border-processed/30", help: "Identical characters recorded under different identifier types." },
  strong: { label: "Strong", tone: "blue", border: "border-sky-500/30", help: "The same digits, with a prefix missing on one side." },
  weak: { label: "Weak", tone: "neutral", border: "border-navy-700", help: "One digit differs in machine-read text; often two different records." },
  conflicting: { label: "Conflicting", tone: "amber", border: "border-inconsistency/30", help: "Signals point both ways, e.g. the same name with different e-mail addresses." },
};

function EntityPanel({
  caseId,
  entityId,
  version,
  onChanged,
  onSelect,
}: {
  caseId: string;
  entityId: string;
  version: number;
  onChanged: () => void;
  onSelect: (id: string) => void;
}) {
  const { data, error, loading, reload, setData } = useApi(
    (signal) => getEntity(caseId, entityId, signal),
    [caseId, entityId, version],
    "Could not load this entity.",
  );
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [reviewer] = useReviewer();

  async function act(action: EntityAction) {
    setBusy(action);
    setActionError(null);
    try {
      const updated: EntityDetail = await reviewEntity(caseId, entityId, {
        action,
        note: note.trim() || undefined,
        reviewer: reviewer || undefined,
      });
      setData(updated);
      setNote("");
      onChanged();
    } catch (err) {
      setActionError(errorText(err, "The decision could not be saved."));
    } finally {
      setBusy(null);
    }
  }

  if (loading && !data) return <LoadingState />;
  if (error && !data) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-lg font-semibold text-slate-100">{data.display_name}</h3>
        <Badge>{data.entity_type}</Badge>
        <Badge tone={RESOLUTION_TONE[data.resolution_status]}>{data.resolution_status}</Badge>
      </div>
      <p className="mt-1 text-xs text-slate-500">
        Normalized key <span className="font-mono text-slate-300">{data.normalized_key}</span> ·{" "}
        {data.evidence_count} evidence item{data.evidence_count === 1 ? "" : "s"} · {data.mention_count} mention
        {data.mention_count === 1 ? "" : "s"}
      </p>
      {data.aliases.length > 0 && (
        <p className="mt-1 text-xs text-slate-400">
          Written as: {data.aliases.map((a) => `“${a}”`).join(", ")}
        </p>
      )}
      {data.merged_into_id && (
        <p className="mt-2 text-xs text-sky-300">
          Merged by a reviewer into{" "}
          <button type="button" className="underline" onClick={() => onSelect(data.merged_into_id!)}>
            another entity
          </button>
          . The original mentions are kept unchanged.
        </p>
      )}
      {data.merged_from.length > 0 && (
        <p className="mt-2 text-xs text-slate-400">
          Merged into this record: {data.merged_from.map((e) => e.display_name).join(", ")}
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {data.resolution_status !== "merged" && data.resolution_status !== "confirmed" && (
          <button type="button" className={BUTTON} disabled={busy !== null} onClick={() => void act("confirm")}>
            Confirm entity
          </button>
        )}
        {data.resolution_status !== "merged" && data.resolution_status !== "rejected" && (
          <button type="button" className={BUTTON} disabled={busy !== null} onClick={() => void act("reject")}>
            Reject (not a real entity)
          </button>
        )}
        {data.resolution_status === "merged" && (
          <button type="button" className={BUTTON} disabled={busy !== null} onClick={() => void act("unmerge")}>
            Unmerge
          </button>
        )}
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note" maxLength={4000} className={`${INPUT} w-48 py-1 text-xs`} />
        <button type="button" className={BUTTON} disabled={busy !== null || !note.trim()} onClick={() => void act("note")}>
          Add note
        </button>
      </div>
      {actionError && <p role="alert" className="mt-2 text-xs text-failed">{actionError}</p>}

      {data.candidates.length > 0 && (
        <p className="mt-3 text-xs text-inconsistency">
          {data.candidates.length} possible duplicate{data.candidates.length === 1 ? "" : "s"}; see the list on the left.
        </p>
      )}

      <p className="mt-4 text-sm font-medium text-slate-200">Mentions ({data.mentions.length})</p>
      <ul className="mt-2 space-y-2">
        {data.mentions.map((m) => (
          <li key={`${m.claim_id}-${m.mention_text}`} className="rounded-md border border-navy-800 bg-navy-950/60 p-3 text-sm">
            <p className="text-xs text-slate-500">
              {m.claim.evidence_name} · {m.claim.modality} · {sourceLabel(m.claim.locator)}
              {m.role ? ` · ${m.role}` : ""} · written as “{m.mention_text}”
            </p>
            <p className="mt-1 whitespace-pre-wrap break-words font-mono text-[13px] text-slate-100">{m.claim.quote}</p>
            {m.claim.segment_id && (
              <Link
                className={`${BUTTON} mt-2`}
                href={sourceHref(caseId, {
                  evidenceId: m.claim.evidence_id,
                  segmentId: m.claim.segment_id,
                  claimId: m.claim.id,
                  locator: m.claim.locator,
                })}
              >
                Open source
              </Link>
            )}
          </li>
        ))}
      </ul>

      <p className="mt-4 text-sm font-medium text-slate-200">Review history</p>
      <HistoryList items={data.history} />
    </Card>
  );
}

export default function EntitiesPage() {
  return (
    <Suspense fallback={<LoadingState />}>
      <EntitiesView />
    </Suspense>
  );
}
