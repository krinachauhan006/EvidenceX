"use client";

import { useState } from "react";
import { Fingerprint, Loader2, ShieldAlert, ShieldCheck } from "lucide-react";
import { reviewHistory } from "@/lib/api/analysis";
import { verifyAudit } from "@/lib/api/phase2";
import { formatDateTime } from "@/lib/format";
import { useCaseContext } from "@/components/cases/case-shell";
import { actionLabel } from "@/components/analysis/review-labels";
import {
  Badge,
  BUTTON,
  Card,
  EmptyState,
  ErrorState,
  InfoTip,
  INPUT,
  SectionHeader,
  Skeleton,
} from "@/components/ui/primitives";
import { useApi } from "@/hooks/use-api";

const SELECT = `${INPUT} w-auto py-1 text-xs`;

export default function AuditPage() {
  const { caseItem } = useCaseContext();
  const caseId = caseItem.id;
  const [target, setTarget] = useState("");
  const [version, setVersion] = useState(0);
  const chain = useApi((signal) => verifyAudit(caseId, signal), [caseId, version], "Could not verify the audit trail.");
  const log = useApi(
    (signal) => reviewHistory(caseId, { targetType: target || undefined, limit: 500 }, signal),
    [caseId, target, version],
    "Could not load the audit trail.",
  );

  return (
    <div>
      <SectionHeader
        title="Audit trail"
        description="Every review decision, membership change and consent change is recorded with the signed-in account that made it. Each record includes a hash of the previous one, so a later edit or deletion breaks the chain and is detected here."
        actions={
          <button type="button" className={BUTTON} onClick={() => setVersion((n) => n + 1)} disabled={chain.loading}>
            {chain.loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Fingerprint className="h-3.5 w-3.5" aria-hidden />}
            Verify again
          </button>
        }
      />
      {chain.error && <ErrorState message={chain.error} onRetry={chain.reload} />}
      {chain.data && (
        <Card className={`mb-5 flex flex-wrap items-center gap-4 p-4 ${chain.data.intact ? "border-processed/30" : "border-failed/40"}`}>
          <div
            className={`flex h-12 w-12 items-center justify-center rounded-full border ${chain.data.intact ? "border-processed/40 bg-processed/10 text-processed" : "border-failed/40 bg-failed/10 text-failed"}`}
          >
            {chain.data.intact ? <ShieldCheck className="h-6 w-6" aria-hidden /> : <ShieldAlert className="h-6 w-6" aria-hidden />}
          </div>
          <div className="min-w-0 flex-1">
            <p className="font-medium text-slate-100">
              {chain.data.intact ? "Audit chain intact" : "Audit chain broken"}
            </p>
            <p className="text-xs text-slate-400">
              {chain.data.checked} chained record{chain.data.checked === 1 ? "" : "s"} checked
              {chain.data.legacy_unchained > 0 &&
                ` · ${chain.data.legacy_unchained} earlier record(s) from before chaining was introduced (kept, not chained)`}
              {!chain.data.intact && chain.data.reason ? ` · ${chain.data.reason} (record ${chain.data.broken_at})` : ""}
            </p>
          </div>
          {chain.data.head && (
            <p className="font-mono text-[11px] text-slate-500" title={chain.data.head}>
              head {chain.data.head.slice(0, 16)}…{" "}
              <InfoTip text="The hash of the newest record. Note it down to check later that no record was changed since." />
            </p>
          )}
        </Card>
      )}

      <div className="mb-3 flex items-center gap-2">
        <select className={SELECT} value={target} onChange={(e) => setTarget(e.target.value)} aria-label="Record type">
          <option value="">All record types</option>
          {["claim", "contradiction", "entity", "event", "relationship", "segment", "case", "case_member"].map((t) => (
            <option key={t} value={t}>
              {t.replace(/_/g, " ")}
            </option>
          ))}
        </select>
        {log.data && <span className="text-xs text-slate-500">{log.data.total} record(s)</span>}
      </div>
      {log.loading && !log.data && <Skeleton rows={5} />}
      {log.error && <ErrorState message={log.error} onRetry={log.reload} />}
      {log.data && log.data.items.length === 0 && <EmptyState title="No recorded actions yet" />}
      {log.data && log.data.items.length > 0 && (
        <Card className="overflow-x-auto">
          <table className="w-full min-w-[42rem] text-left text-xs">
            <thead className="border-b border-navy-800 text-[11px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="px-3 py-2 font-medium">When</th>
                <th className="px-3 py-2 font-medium">Action</th>
                <th className="px-3 py-2 font-medium">On</th>
                <th className="px-3 py-2 font-medium">Change</th>
                <th className="px-3 py-2 font-medium">By</th>
                <th className="px-3 py-2 font-medium">Note</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-navy-800">
              {log.data.items.map((a) => (
                <tr key={a.id} className="align-top hover:bg-white/[0.02]">
                  <td className="whitespace-nowrap px-3 py-2 tabular-nums text-slate-400">{formatDateTime(a.created_at)}</td>
                  <td className="px-3 py-2 text-slate-200">{actionLabel(a.action)}</td>
                  <td className="px-3 py-2">
                    <Badge>{a.target_type.replace(/_/g, " ")}</Badge>
                  </td>
                  <td className="px-3 py-2 text-slate-400">
                    {a.from_status || a.to_status ? `${a.from_status ?? "—"} → ${a.to_status ?? "—"}` : "—"}
                  </td>
                  <td className="px-3 py-2 text-slate-300">{a.reviewer ?? "not recorded"}</td>
                  <td className="max-w-[18rem] px-3 py-2 text-slate-400">{a.note ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
