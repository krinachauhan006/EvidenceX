"use client";

import { useState } from "react";
import Link from "next/link";
import clsx from "clsx";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  CircleSlash,
  Link2,
  Loader2,
  RotateCcw,
  Unlink,
  X,
} from "lucide-react";
import { reviewEvent } from "@/lib/api/phase2";
import type { EventAction, EventDetail, InvestigationEvent } from "@/lib/types/phase2";
import { hasRole, type Role } from "@/lib/types/case";
import { sourceHref } from "@/components/analysis/source-link";
import { sourceLabel } from "@/components/analysis/claim-card";
import { percent } from "@/components/analysis/review-labels";
import {
  ANCHOR_LABEL,
  axisBounds,
  claimInterval,
  comparisonLabel,
  eventStatusTone,
  hhmm,
} from "@/components/events/event-labels";
import { Badge, BUTTON, Card, InfoTip, INPUT } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { errorText } from "@/hooks/use-api";

const PALETTE = ["#38bdf8", "#a78bfa", "#34d399", "#f472b6", "#facc15", "#fb923c"];

/**
 * One proposed or confirmed event: why the rules grouped these claims, what is
 * missing, how each pair of accounts compares, and the reviewer's decision.
 * Accounts are only compared for findings after a reviewer confirms the grouping.
 */
export function EventCard({
  caseId,
  event,
  role,
  defaultOpen = false,
  onChanged,
}: {
  caseId: string;
  event: InvestigationEvent;
  role: Role | null;
  defaultOpen?: boolean;
  onChanged: (updated: EventDetail) => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const notify = useToast();
  const canReview = hasRole(role, "reviewer");
  const candidates = event.comparisons.filter((c) => c.is_candidate).length;

  async function act(action: EventAction, extra: { claim_id?: string; claim_ids?: string[] } = {}) {
    setBusy(action + (extra.claim_id ?? ""));
    setError(null);
    try {
      const updated = await reviewEvent(caseId, event.id, { action, note: note.trim() || undefined, ...extra });
      setNote("");
      onChanged(updated);
      const msg: Record<string, string> = {
        confirm: "Event confirmed: its accounts are now compared",
        reject: "Grouping rejected",
        reopen: "Event reopened for review",
        note: "Note added",
        remove_claim: "Claim removed from the event",
        split: "Claims split into a new event",
      };
      notify("success", msg[action] ?? "Saved", action === "confirm" && candidates ? `${candidates} pair(s) may need review as inconsistencies.` : undefined);
    } catch (err) {
      const text = errorText(err, "The decision could not be saved.");
      setError(text);
      notify("error", "Not saved", text);
    } finally {
      setBusy(null);
    }
  }

  const intervals = event.members
    .map((m) => claimInterval(m.claim.event_time))
    .filter((x): x is [number, number] => x !== null);
  const [lo, hi] = axisBounds(intervals);
  const x = (m: number) => `${((m - lo) / (hi - lo || 1)) * 100}%`;
  const colour = new Map(event.members.map((m, i) => [m.claim.id, PALETTE[i % PALETTE.length]]));

  return (
    <Card
      as="article"
      className={clsx(
        "overflow-hidden transition-colors",
        event.status === "confirmed" && "border-processed/25",
        event.status === "rejected" && "opacity-75",
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-start justify-between gap-3 px-4 py-3 text-left hover:bg-white/[0.02]"
      >
        <span className="min-w-0">
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="font-medium text-slate-100">{event.title}</span>
            <Badge tone={eventStatusTone(event.status)}>{event.status}</Badge>
            <Badge title="Who proposed this grouping">
              {event.origin === "reviewer" ? "grouped by a reviewer" : "proposed by the rules"}
            </Badge>
            {candidates > 0 && (
              <Badge tone="amber">
                <AlertTriangle className="h-3 w-3" aria-hidden /> {candidates} pair{candidates === 1 ? "" : "s"} differ
              </Badge>
            )}
          </span>
          <span className="mt-0.5 block text-xs text-slate-500">
            {event.members.length} accounts · {ANCHOR_LABEL[event.anchor_kind] ?? event.anchor_kind}: {event.anchor_key} ·{" "}
            {event.event_date ?? "date not stated"} · association {percent(event.association_confidence)}{" "}
            <span className="text-slate-600">(heuristic)</span>
          </span>
        </span>
        <ChevronDown className={clsx("mt-1 h-4 w-4 shrink-0 text-slate-500 transition-transform", open && "rotate-180")} aria-hidden />
      </button>

      {intervals.length > 0 && (
        <div className="px-4 pb-3" aria-label="Stated times of each account">
          <div className="relative h-8 rounded-md border border-navy-800 bg-navy-950/70">
            {event.members.map((m) => {
              const iv = claimInterval(m.claim.event_time);
              if (!iv) return null;
              const c = colour.get(m.claim.id)!;
              const dim = hover !== null && hover !== m.claim.id;
              return (
                <span
                  key={m.claim.id}
                  title={`${m.account_label}: ${hhmm(iv[0])}${iv[1] !== iv[0] ? `–${hhmm(iv[1])}` : ""}`}
                  onMouseEnter={() => setHover(m.claim.id)}
                  onMouseLeave={() => setHover(null)}
                  className="absolute top-1/2 h-3 -translate-y-1/2 rounded-full border transition-opacity"
                  style={{
                    left: x(iv[0]),
                    width: iv[1] === iv[0] ? "12px" : `calc(${x(iv[1])} - ${x(iv[0])})`,
                    marginLeft: iv[1] === iv[0] ? "-6px" : 0,
                    background: `${c}55`,
                    borderColor: c,
                    opacity: dim ? 0.25 : 1,
                  }}
                />
              );
            })}
          </div>
          <div className="mt-0.5 flex justify-between text-[10px] tabular-nums text-slate-600">
            <span>{hhmm(lo)}</span>
            <span>{hhmm(hi)}</span>
          </div>
        </div>
      )}

      {open && (
        <div className="evx-page space-y-4 border-t border-navy-800 px-4 py-4">
          <section>
            <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Accounts</p>
            <ul className="mt-2 space-y-2">
              {event.members.map((m) => (
                <li
                  key={m.claim.id}
                  onMouseEnter={() => setHover(m.claim.id)}
                  onMouseLeave={() => setHover(null)}
                  className={clsx(
                    "rounded-lg border bg-navy-950/60 p-3 transition-colors",
                    hover === m.claim.id ? "border-sky-500/40" : "border-navy-800",
                  )}
                >
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ background: colour.get(m.claim.id) }} aria-hidden />
                    <span className="font-medium text-slate-200">{m.account_label}</span>
                    <span className="text-slate-500">
                      {m.claim.modality} · {sourceLabel(m.claim.locator)} · date {m.date ?? "not stated"} ({m.date_precision.replace(/_/g, " ")})
                    </span>
                    {m.added_by === "reviewer" && <Badge>added by a reviewer</Badge>}
                  </div>
                  <blockquote className="mt-1.5 whitespace-pre-wrap break-words border-l-2 border-slate-600 pl-2 font-mono text-[13px] text-slate-100">
                    {m.claim.quote}
                  </blockquote>
                  <p className="mt-1 text-[11px] text-slate-500">Why included: {m.match_reasons.join("; ")}</p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {m.claim.segment_id && (
                      <Link
                        className={BUTTON}
                        href={sourceHref(caseId, {
                          evidenceId: m.claim.evidence_id,
                          segmentId: m.claim.segment_id,
                          claimId: m.claim.id,
                          locator: m.claim.locator,
                        })}
                      >
                        <Link2 className="h-3 w-3" aria-hidden /> Open source
                      </Link>
                    )}
                    {canReview && event.status === "proposed" && event.members.length > 2 && (
                      <button
                        type="button"
                        className={BUTTON}
                        disabled={busy !== null}
                        onClick={() => void act("remove_claim", { claim_id: m.claim.id })}
                      >
                        <Unlink className="h-3 w-3" aria-hidden /> Not part of this event
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </section>

          <section>
            <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-slate-500">
              How the accounts compare
              <InfoTip text="Each pair of accounts is classified by the rules. Only pairs marked as appearing to conflict can become potential inconsistencies, and only after a reviewer confirms the event." />
            </p>
            <ul className="mt-2 grid gap-2 md:grid-cols-2">
              {event.comparisons.map((c) => {
                const l = comparisonLabel(c.classification);
                return (
                  <li key={`${c.claim_a_id}-${c.claim_b_id}`} className="rounded-lg border border-navy-800 bg-navy-950/60 p-2.5 text-xs">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge tone={l.tone} title={l.help}>
                        {l.label}
                      </Badge>
                      {c.gap_minutes !== null && <span className="tabular-nums text-slate-400">{c.gap_minutes} min apart</span>}
                    </div>
                    <p className="mt-1 text-slate-400">
                      <span className="text-slate-300">{c.account_a}</span> vs <span className="text-slate-300">{c.account_b}</span>
                    </p>
                    <p className="mt-1 text-slate-500">{c.explanation}</p>
                  </li>
                );
              })}
            </ul>
          </section>

          <div className="grid gap-4 md:grid-cols-2">
            <section>
              <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Association score factors</p>
              <ul className="mt-1.5 space-y-1 text-xs">
                {event.factors.map((f) => (
                  <li key={f.factor} className="flex justify-between gap-2 text-slate-400">
                    <span>
                      <span className="text-slate-300">{f.factor}</span> · {f.detail}
                    </span>
                    <span className={clsx("tabular-nums", f.effect < 0 ? "text-failed" : "text-processed")}>
                      {f.effect > 0 ? "+" : ""}
                      {f.effect.toFixed(2)}
                    </span>
                  </li>
                ))}
              </ul>
              <p className="mt-1 text-[11px] text-slate-600">
                A heuristic ordering aid, not a probability that this event happened.
              </p>
            </section>
            <section>
              <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Missing links</p>
              {event.missing_links.length === 0 ? (
                <p className="mt-1.5 text-xs text-slate-500">None recorded.</p>
              ) : (
                <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-xs text-slate-400">
                  {event.missing_links.map((m) => (
                    <li key={m}>{m}</li>
                  ))}
                </ul>
              )}
            </section>
          </div>

          {event.contradiction_ids.length > 0 && (
            <Link
              href={`/cases/${caseId}/contradictions`}
              className="flex items-center gap-2 rounded-lg border border-inconsistency/30 bg-inconsistency/5 px-3 py-2 text-xs text-inconsistency hover:bg-inconsistency/10"
            >
              <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
              {event.contradiction_ids.length} potential inconsistenc{event.contradiction_ids.length === 1 ? "y" : "ies"} came from
              this event. Review them →
            </Link>
          )}

          {event.review_note && (
            <p className="text-xs text-slate-400">
              Reviewer note: <span className="text-slate-200">{event.review_note}</span>
              {event.reviewed_by ? ` · ${event.reviewed_by}` : ""}
            </p>
          )}

          {canReview ? (
            <div className="flex flex-wrap items-center gap-1.5 border-t border-navy-800 pt-3">
              {event.status === "proposed" && (
                <>
                  <button type="button" className={`${BUTTON} border-processed/40 text-processed`} disabled={busy !== null} onClick={() => void act("confirm")}>
                    {busy === "confirm" ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> : <Check className="h-3 w-3" aria-hidden />}
                    Same occurrence: confirm
                  </button>
                  <button type="button" className={BUTTON} disabled={busy !== null} onClick={() => void act("reject")}>
                    <X className="h-3 w-3" aria-hidden /> Different occurrences: reject
                  </button>
                </>
              )}
              {event.status !== "proposed" && (
                <button type="button" className={BUTTON} disabled={busy !== null} onClick={() => void act("reopen")}>
                  <RotateCcw className="h-3 w-3" aria-hidden /> Reopen
                </button>
              )}
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Note (why?)"
                maxLength={4000}
                className={`${INPUT} w-56 py-1 text-xs`}
                aria-label="Review note"
              />
              <button type="button" className={BUTTON} disabled={busy !== null || !note.trim()} onClick={() => void act("note")}>
                Add note
              </button>
            </div>
          ) : (
            <p className="flex items-center gap-1.5 border-t border-navy-800 pt-3 text-xs text-slate-500">
              <CircleSlash className="h-3.5 w-3.5" aria-hidden /> Your role can view events but not review them.
            </p>
          )}
          {error && (
            <p role="alert" className="text-xs text-failed">
              {error}
            </p>
          )}
        </div>
      )}
    </Card>
  );
}
