"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertTriangle, Crosshair, Loader2, Quote } from "lucide-react";
import { reviewClaim } from "@/lib/api/analysis";
import type { Claim, ClaimAction } from "@/lib/types/analysis";
import type { Locator } from "@/lib/types/processing";
import { describeLocator } from "@/components/evidence/source-reference";
import {
  actionLabel,
  claimActions,
  claimStatus,
  eventTimeLabel,
  methodLabel,
  percent,
} from "@/components/analysis/review-labels";
import { sourceHref } from "@/components/analysis/source-link";
import { Badge, BUTTON, INPUT } from "@/components/ui/primitives";
import { errorText } from "@/hooks/use-api";
import { useReviewer } from "@/hooks/use-reviewer";

interface Props {
  caseId: string;
  claim: Claim;
  /** Show which evidence item the claim comes from (lists spanning many files). */
  showEvidence?: boolean;
  /** In the workspace, jump to the source in-page instead of following a link. */
  onShowSource?: (claim: Claim) => void;
  onChanged?: (claim: Claim) => void;
  compact?: boolean;
}

export function sourceLabel(locator: Record<string, unknown> | null): string {
  return describeLocator(locator as unknown as Locator).label;
}

export function ClaimCard({ caseId, claim, showEvidence, onShowSource, onChanged, compact }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(claim.reviewed_text ?? claim.claim_text);
  const [note, setNote] = useState("");
  const [reviewer] = useReviewer();
  const status = claimStatus(claim.review_status);
  const time = eventTimeLabel(claim.event_time);

  async function act(action: ClaimAction) {
    setBusy(action);
    setError(null);
    try {
      const updated = await reviewClaim(caseId, claim.id, {
        action,
        note: note.trim() || undefined,
        reviewer: reviewer || undefined,
        reviewed_text: action === "edit" ? text.trim() : undefined,
      });
      setNote("");
      setEditing(false);
      onChanged?.(updated);
    } catch (err) {
      setError(errorText(err, "The review could not be saved."));
    } finally {
      setBusy(null);
    }
  }

  const source = (
    <>
      <Crosshair className="h-3.5 w-3.5" aria-hidden /> Show in source
    </>
  );

  return (
    <article className="rounded-lg border border-navy-800 bg-navy-900/70 p-4">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone={status.tone}>{status.label}</Badge>
        <Badge>{claim.claim_type.replace(/_/g, " ")}</Badge>
        <Badge>{claim.modality}</Badge>
        {claim.contradiction_count > 0 && (
          <Badge tone="amber" title="Part of a potential inconsistency awaiting human review">
            <AlertTriangle className="h-3 w-3" aria-hidden />
            {claim.contradiction_count} potential inconsistenc
            {claim.contradiction_count === 1 ? "y" : "ies"}
          </Badge>
        )}
        {claim.grounding !== "grounded" && (
          <Badge tone="red" title="The quote could not be matched to the source text">
            Source match insufficient
          </Badge>
        )}
        {!claim.source_current && (
          <Badge title="The evidence was reprocessed after this claim was extracted">
            From earlier run {claim.run_number}
          </Badge>
        )}
        {claim.is_inferred && <Badge tone="amber">Inferred, not stated</Badge>}
      </div>

      {showEvidence && (
        <p className="mt-2 text-xs text-slate-500">
          {claim.evidence_name} · {sourceLabel(claim.locator)}
        </p>
      )}

      <div className="mt-2">
        <p className="text-[11px] uppercase tracking-wider text-slate-500">
          Machine interpretation · {methodLabel(claim.extraction_method)}
        </p>
        <p className="mt-0.5 text-sm text-slate-200">{claim.claim_text}</p>
        {claim.reviewed_text && (
          <div className="mt-2 rounded-md border border-processed/30 bg-processed/5 px-3 py-2">
            <p className="text-[11px] uppercase tracking-wider text-processed">
              Reviewer&apos;s interpretation
              {claim.reviewed_by ? ` · ${claim.reviewed_by}` : ""}
            </p>
            <p className="mt-0.5 text-sm text-slate-200">{claim.reviewed_text}</p>
          </div>
        )}
      </div>

      <blockquote className="mt-3 rounded-md border-l-2 border-slate-500 bg-navy-950/70 px-3 py-2">
        <p className="flex items-center gap-1 text-[11px] uppercase tracking-wider text-slate-500">
          <Quote className="h-3 w-3" aria-hidden /> Exact source quote · {sourceLabel(claim.locator)}
        </p>
        <p className="mt-1 whitespace-pre-wrap break-words font-mono text-[13px] text-slate-100">
          {claim.quote}
        </p>
      </blockquote>

      {!compact && (
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-3">
          {claim.subject && <Fact label="Subject">{claim.subject}</Fact>}
          {claim.predicate && <Fact label="Predicate">{claim.predicate}</Fact>}
          {time && <Fact label="Time as written">{time}</Fact>}
          {claim.location && <Fact label="Location">{claim.location}</Fact>}
          {claim.source_engine_confidence !== null && (
            <Fact label="Engine confidence (OCR/ASR self-report)">
              {percent(claim.source_engine_confidence)}
            </Fact>
          )}
          <Fact label="Extraction confidence">
            {claim.extraction_confidence === null
              ? "not applicable (rule-based)"
              : `${percent(claim.extraction_confidence)} (model self-assessment)`}
          </Fact>
        </dl>
      )}

      {claim.uncertainty.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs text-inconsistency/90">
          {claim.uncertainty.map((u) => (
            <li key={u}>• {u}</li>
          ))}
        </ul>
      )}

      {claim.entities.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {claim.entities.map((m) => (
            <Link
              key={`${m.entity_id}-${m.mention_text}`}
              href={`/cases/${caseId}/entities?focus=${m.entity_id}`}
              className="rounded border border-navy-700 bg-navy-800 px-1.5 py-0.5 text-[11px] text-slate-300 hover:border-navy-600"
              title={`${m.entity_type}: mentioned as "${m.mention_text}"`}
            >
              {m.entity_type} · {m.display_name}
            </Link>
          ))}
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {claim.segment_id &&
          (onShowSource ? (
            <button type="button" className={BUTTON} onClick={() => onShowSource(claim)}>
              {source}
            </button>
          ) : (
            <Link
              className={BUTTON}
              href={sourceHref(caseId, {
                evidenceId: claim.evidence_id,
                segmentId: claim.segment_id,
                claimId: claim.id,
                locator: claim.locator,
              })}
            >
              {source}
            </Link>
          ))}
        {claimActions(claim.review_status).map((a) => (
          <button
            key={a}
            type="button"
            disabled={busy !== null}
            onClick={() => void act(a)}
            className={BUTTON}
          >
            {busy === a && <Loader2 className="h-3 w-3 animate-spin" aria-hidden />}
            {actionLabel(a)}
          </button>
        ))}
        <button type="button" className={BUTTON} onClick={() => setEditing((v) => !v)}>
          {editing ? "Cancel" : "Edit interpretation / note"}
        </button>
      </div>

      {editing && (
        <div className="mt-3 space-y-2 rounded-md border border-navy-800 bg-navy-950/60 p-3">
          <label className="block text-xs text-slate-400">
            Reviewer&apos;s interpretation (the machine text and quote stay unchanged)
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={2}
              maxLength={4000}
              className={`${INPUT} mt-1`}
            />
          </label>
          <label className="block text-xs text-slate-400">
            Note
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={4000}
              className={`${INPUT} mt-1`}
            />
          </label>
          <div className="flex gap-1.5">
            <button
              type="button"
              disabled={busy !== null || !text.trim()}
              onClick={() => void act("edit")}
              className={BUTTON}
            >
              Save interpretation
            </button>
            <button
              type="button"
              disabled={busy !== null || !note.trim()}
              onClick={() => void act("note")}
              className={BUTTON}
            >
              Add note only
            </button>
          </div>
        </div>
      )}

      {error && (
        <p role="alert" className="mt-2 text-xs text-failed">
          {error}
        </p>
      )}
    </article>
  );
}

export function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-slate-500">{label}</dt>
      <dd className="break-words text-slate-200">{children}</dd>
    </div>
  );
}
