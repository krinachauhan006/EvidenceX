"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertTriangle, ChevronDown, ChevronRight, Crosshair, History, Loader2 } from "lucide-react";
import { addAlternative, getContradiction, reviewContradiction } from "@/lib/api/analysis";
import type {
  ClaimBrief,
  Contradiction,
  ContradictionAction,
  ReviewAction,
} from "@/lib/types/analysis";
import {
  actionLabel,
  contradictionActions,
  contradictionStatus,
  eventTimeLabel,
  percent,
} from "@/components/analysis/review-labels";
import { sourceHref } from "@/components/analysis/source-link";
import { sourceLabel } from "@/components/analysis/claim-card";
import { Badge, BUTTON, INPUT } from "@/components/ui/primitives";
import { formatDateTime } from "@/lib/format";
import { errorText } from "@/hooks/use-api";
import { useReviewer } from "@/hooks/use-reviewer";

const BASIS_LABEL: Record<string, string> = {
  machine_hypothesis: "Machine hypothesis (not source-supported)",
  source_supported: "Source-supported",
  human: "Added by a reviewer",
};

function Side({ caseId, title, claim }: { caseId: string; title: string; claim: ClaimBrief }) {
  const time = eventTimeLabel(claim.event_time);
  return (
    <div className="min-w-0 rounded-md border border-navy-800 bg-navy-950/60 p-3">
      <p className="text-[11px] uppercase tracking-wider text-slate-500">{title}</p>
      <p className="mt-1 truncate text-sm font-medium text-slate-100" title={claim.evidence_name}>
        {claim.evidence_name}
      </p>
      <p className="text-xs text-slate-500">
        {claim.modality} · {sourceLabel(claim.locator)}
      </p>
      <p className="mt-2 whitespace-pre-wrap break-words font-mono text-[13px] text-slate-100">
        “{claim.quote}”
      </p>
      {time && <p className="mt-1 text-xs text-slate-400">Time as written: {time}</p>}
      {claim.segment_id && (
        <Link
          href={sourceHref(caseId, {
            evidenceId: claim.evidence_id,
            segmentId: claim.segment_id,
            claimId: claim.id,
            locator: claim.locator,
          })}
          className={`${BUTTON} mt-2`}
        >
          <Crosshair className="h-3.5 w-3.5" aria-hidden /> Open source
        </Link>
      )}
    </div>
  );
}

interface Props {
  caseId: string;
  item: Contradiction;
  onChanged?: (item: Contradiction) => void;
  defaultOpen?: boolean;
}

export function ContradictionCard({ caseId, item, onChanged, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [altText, setAltText] = useState("");
  const [history, setHistory] = useState<ReviewAction[] | null>(null);
  const [reviewer] = useReviewer();
  const status = contradictionStatus(item.review_status);
  const exp = item.explanation;

  async function act(action: ContradictionAction) {
    setBusy(action);
    setError(null);
    try {
      const updated = await reviewContradiction(caseId, item.id, {
        action,
        note: note.trim() || undefined,
        reviewer: reviewer || undefined,
      });
      setNote("");
      setHistory(updated.history);
      onChanged?.(updated);
    } catch (err) {
      setError(errorText(err, "The review could not be saved."));
    } finally {
      setBusy(null);
    }
  }

  async function saveAlternative() {
    setBusy("alt");
    setError(null);
    try {
      const updated = await addAlternative(caseId, item.id, {
        explanation: altText.trim(),
        author: reviewer || undefined,
      });
      setAltText("");
      setHistory(updated.history);
      onChanged?.(updated);
    } catch (err) {
      setError(errorText(err, "The alternative explanation could not be saved."));
    } finally {
      setBusy(null);
    }
  }

  async function loadHistory() {
    try {
      setHistory((await getContradiction(caseId, item.id)).history);
    } catch (err) {
      setError(errorText(err, "Could not load the review history."));
    }
  }

  return (
    <article className="rounded-lg border border-inconsistency/25 bg-navy-900/70">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-start gap-3 p-4 text-left"
      >
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-inconsistency" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-sm font-medium text-slate-100">
              Potential {item.category} inconsistency
              {item.via_entity_name ? ` · ${item.via_entity_name}` : ""}
            </span>
            <Badge tone={status.tone}>{status.label}</Badge>
            <Badge title="Rule severity: size of the difference, not importance or truth">
              {item.severity} severity
            </Badge>
            <Badge title="How cleanly the rule matched. Not the probability that a source is wrong.">
              Detection confidence {percent(item.detection_confidence)}
            </Badge>
            {!item.claims_current && (
              <Badge title="One of the sources was reprocessed after detection">
                Based on an earlier run
              </Badge>
            )}
          </div>
          <p className="mt-1 text-sm text-slate-400">{exp.why}</p>
        </div>
        {open ? (
          <ChevronDown className="h-4 w-4 text-slate-500" aria-hidden />
        ) : (
          <ChevronRight className="h-4 w-4 text-slate-500" aria-hidden />
        )}
      </button>

      {open && (
        <div className="space-y-4 border-t border-navy-800 p-4">
          <div className="grid gap-3 md:grid-cols-2">
            <Side caseId={caseId} title="First source states" claim={item.claim_a} />
            <Side caseId={caseId} title="Second source states" claim={item.claim_b} />
          </div>

          <dl className="grid gap-3 text-sm md:grid-cols-3">
            <div>
              <dt className="text-[11px] uppercase tracking-wider text-slate-500">
                Why they may be inconsistent
              </dt>
              <dd className="mt-0.5 text-slate-200">{exp.why}</dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-wider text-slate-500">
                What is uncertain
              </dt>
              <dd className="mt-0.5 text-slate-200">{exp.uncertain}</dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-wider text-slate-500">
                What would resolve it
              </dt>
              <dd className="mt-0.5 text-slate-200">{exp.would_resolve}</dd>
            </div>
          </dl>

          {item.uncertainty.length > 0 && (
            <ul className="space-y-0.5 text-xs text-inconsistency/90">
              {item.uncertainty.map((u) => (
                <li key={u}>• {u}</li>
              ))}
            </ul>
          )}

          <div>
            <p className="text-xs font-medium text-slate-300">
              Alternative explanations ({item.alternatives.length})
            </p>
            <p className="text-xs text-slate-500">
              The difference may be benign. Machine hypotheses are suggestions to check, not
              findings.
            </p>
            <ul className="mt-2 space-y-2">
              {item.alternatives.map((a) => (
                <li key={a.id} className="rounded-md border border-navy-800 bg-navy-950/60 p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge tone={a.basis === "human" ? "blue" : "neutral"}>
                      {BASIS_LABEL[a.basis] ?? a.basis}
                    </Badge>
                    {a.author && <span className="text-xs text-slate-500">{a.author}</span>}
                  </div>
                  <p className="mt-1 text-slate-200">{a.explanation}</p>
                  <dl className="mt-1 grid gap-x-4 gap-y-0.5 text-xs text-slate-400 md:grid-cols-2">
                    {a.supporting_evidence && (
                      <div>
                        <dt className="inline text-slate-500">Supporting: </dt>
                        <dd className="inline">{a.supporting_evidence}</dd>
                      </div>
                    )}
                    {a.weakening_evidence && (
                      <div>
                        <dt className="inline text-slate-500">Would weaken it: </dt>
                        <dd className="inline">{a.weakening_evidence}</dd>
                      </div>
                    )}
                    {a.missing_information && (
                      <div>
                        <dt className="inline text-slate-500">Missing: </dt>
                        <dd className="inline">{a.missing_information}</dd>
                      </div>
                    )}
                    {a.verification_recommendation && (
                      <div>
                        <dt className="inline text-slate-500">To verify: </dt>
                        <dd className="inline">{a.verification_recommendation}</dd>
                      </div>
                    )}
                  </dl>
                </li>
              ))}
            </ul>
            <div className="mt-2 flex gap-2">
              <input
                value={altText}
                onChange={(e) => setAltText(e.target.value)}
                placeholder="Add an alternative explanation…"
                maxLength={4000}
                className={INPUT}
              />
              <button
                type="button"
                disabled={busy !== null || !altText.trim()}
                onClick={() => void saveAlternative()}
                className={BUTTON}
              >
                Add
              </button>
            </div>
          </div>

          <div className="rounded-md border border-navy-800 bg-navy-950/60 p-3">
            <p className="text-xs font-medium text-slate-300">Human review</p>
            <p className="text-xs text-slate-500">
              Confirming records that the sources disagree. It does not say which source is
              right, and it is not a finding about anyone&apos;s conduct.
            </p>
            {item.resolution_note && (
              <p className="mt-2 text-sm text-processed">Resolution: {item.resolution_note}</p>
            )}
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Note (required to resolve)"
              maxLength={4000}
              className={`${INPUT} mt-2`}
            />
            <div className="mt-2 flex flex-wrap gap-1.5">
              {contradictionActions(item.review_status).map((a) => (
                <button
                  key={a}
                  type="button"
                  disabled={busy !== null || (a === "resolve" && !note.trim())}
                  onClick={() => void act(a)}
                  className={BUTTON}
                >
                  {busy === a && <Loader2 className="h-3 w-3 animate-spin" aria-hidden />}
                  {actionLabel(a)}
                </button>
              ))}
              <button
                type="button"
                disabled={busy !== null || !note.trim()}
                onClick={() => void act("note")}
                className={BUTTON}
              >
                Add note
              </button>
              <button type="button" onClick={() => void loadHistory()} className={BUTTON}>
                <History className="h-3.5 w-3.5" aria-hidden /> History
              </button>
            </div>
            {error && (
              <p role="alert" className="mt-2 text-xs text-failed">
                {error}
              </p>
            )}
            {history && <HistoryList items={history} />}
          </div>
        </div>
      )}
    </article>
  );
}

export function HistoryList({ items }: { items: ReviewAction[] }) {
  if (items.length === 0) {
    return <p className="mt-2 text-xs text-slate-500">No review actions yet.</p>;
  }
  return (
    <ol className="mt-2 space-y-1 border-l border-navy-700 pl-3">
      {items.map((h) => (
        <li key={h.id} className="text-xs text-slate-400">
          <span className="text-slate-200">{actionLabel(h.action)}</span>
          {h.from_status && h.to_status && h.from_status !== h.to_status && (
            <span>
              {" "}
              ({h.from_status} → {h.to_status})
            </span>
          )}
          <span> · {h.reviewer ?? "unspecified"} · {formatDateTime(h.created_at)}</span>
          {h.note && <p className="text-slate-300">“{h.note}”</p>}
        </li>
      ))}
    </ol>
  );
}
