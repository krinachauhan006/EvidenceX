"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  Copy,
  Download,
  FileQuestion,
  FileText,
  History,
  Layers,
  Loader2,
  Quote,
  RotateCcw,
} from "lucide-react";
import {
  evidenceAnalysisSummary,
  listAudioModels,
  listClaims,
  listRelationships,
} from "@/lib/api/analysis";
import { evidenceDownloadUrl, getEvidence } from "@/lib/api/evidence";
import { listExtractions, listSegments, processEvidence } from "@/lib/api/processing";
import { formatBytes, formatDateTime, formatDurationMs } from "@/lib/format";
import type { Claim } from "@/lib/types/analysis";
import type { Evidence } from "@/lib/types/evidence";
import type { Extraction, Segment } from "@/lib/types/processing";
import { useCaseContext } from "@/components/cases/case-shell";
import { ClaimCard, Fact, sourceLabel } from "@/components/analysis/claim-card";
import { WORKSPACE_TABS, parseFocus, type WorkspaceTab } from "@/components/analysis/source-link";
import { methodLabel } from "@/components/analysis/review-labels";
import { ExtractionViewer } from "@/components/evidence/extraction-viewer";
import { VideoViewer } from "@/components/workspace/video-viewer";
import { errorCodeLabel, outcomeLabel } from "@/components/evidence/processing-labels";
import {
  Badge,
  BUTTON,
  BUTTON_PRIMARY,
  Card,
  EmptyState,
  ErrorState,
  INPUT,
  LoadingState,
  StatTile,
  Tabs,
} from "@/components/ui/primitives";
import { errorText, useApi } from "@/hooks/use-api";
import { canRetry, errorKind } from "@/components/ui/error-kind";
import { AudioViewer } from "@/components/workspace/audio-viewer";
import { EmailViewer } from "@/components/workspace/email-viewer";
import { ImageViewer } from "@/components/workspace/image-viewer";
import { PdfViewer } from "@/components/workspace/pdf-viewer";
import { TableViewer } from "@/components/workspace/table-viewer";
import type { ViewerProps } from "@/components/workspace/types";

const POLL_MS = 2000;
const SEGMENT_PAGE = 500;
const MAX_SEGMENTS = 5000;

const STATUS_TONE = { pending: "neutral", processing: "amber", completed: "green", failed: "red" } as const;

async function loadAllSegments(caseId: string, evidenceId: string, signal: AbortSignal) {
  const out: Segment[] = [];
  let offset = 0;
  let total = 0;
  do {
    const page = await listSegments(caseId, evidenceId, { limit: SEGMENT_PAGE, offset }, signal);
    out.push(...page.items);
    total = page.total;
    offset += SEGMENT_PAGE;
  } while (offset < total && out.length < MAX_SEGMENTS);
  return { items: out, total, capped: out.length < total };
}

export function EvidenceWorkspace({ evidenceId }: { evidenceId: string }) {
  const { caseItem, analysisVersion } = useCaseContext();
  const caseId = caseItem.id;
  const params = useSearchParams();
  const router = useRouter();
  const initial = useMemo(() => parseFocus((k) => params.get(k)), [params]);
  const [tab, setTab] = useState<WorkspaceTab>(initial.tab);
  const [focusSegment, setFocusSegment] = useState<string | null>(initial.segmentId);
  const [focusTime, setFocusTime] = useState<number | null>(initial.t);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    setTab(initial.tab);
    setFocusSegment(initial.segmentId);
    setFocusTime(initial.t);
  }, [initial]);

  const evidence = useApi(
    () => getEvidence(caseId, evidenceId),
    [caseId, evidenceId, version],
    "This evidence item could not be loaded.",
  );
  const status = evidence.data?.processing_status;

  // Poll while processing so the workspace fills in as soon as results exist.
  useEffect(() => {
    if (status !== "processing") return;
    const t = setTimeout(() => setVersion((n) => n + 1), POLL_MS);
    return () => clearTimeout(t);
  }, [status, evidence.data]);

  const runs = useApi((signal) => listExtractions(caseId, evidenceId, signal), [caseId, evidenceId, version]);
  const current = runs.data?.items.find((r) => r.is_current) ?? null;
  const segments = useApi(
    (signal) => (current ? loadAllSegments(caseId, evidenceId, signal) : Promise.resolve({ items: [], total: 0, capped: false })),
    [caseId, evidenceId, current?.id, version],
    "Could not load the extracted content.",
  );
  const claims = useApi(
    (signal) => listClaims(caseId, { evidenceId, limit: 500 }, signal),
    [caseId, evidenceId, version, analysisVersion],
    "Could not load claims.",
  );
  const summary = useApi(
    (signal) => evidenceAnalysisSummary(caseId, evidenceId, signal),
    [caseId, evidenceId, version, analysisVersion],
  );

  const changeTab = useCallback(
    (next: WorkspaceTab) => {
      setTab(next);
      const qs = new URLSearchParams(params.toString());
      qs.set("tab", next);
      router.replace(`?${qs.toString()}`, { scroll: false });
    },
    [params, router],
  );

  const showSource = useCallback(
    (claim: Claim) => {
      setFocusSegment(claim.segment_id);
      const loc = claim.locator ?? {};
      const t = typeof loc.word_start === "number" ? loc.word_start : typeof loc.start === "number" ? loc.start : null;
      setFocusTime(t);
      changeTab("preview");
    },
    [changeTab],
  );

  if (evidence.loading && !evidence.data) return <LoadingState label="Opening evidence workspace…" />;
  if (evidence.error && !evidence.data) {
    if (errorKind(evidence.errorStatus) === "not_found") {
      return <EvidenceNotFound caseId={caseId} />;
    }
    return (
      <ErrorState
        message="This evidence item could not be loaded."
        onRetry={canRetry(evidence.errorStatus) ? evidence.reload : undefined}
      />
    );
  }
  const e = evidence.data;
  if (!e) return null;

  const claimList = claims.data?.items ?? [];
  const viewerProps: ViewerProps = {
    caseId,
    evidenceId,
    segments: segments.data?.items ?? [],
    claims: claimList,
    focusSegmentId: focusSegment,
    focusTime,
    focusPage: initial.page,
    onFocusSegment: setFocusSegment,
    metadata: current?.doc_metadata ?? {},
    onSegmentsChanged: () => setVersion((n) => n + 1),
  };
  const s = summary.data;

  return (
    <div className="space-y-5">
      <Link href={`/cases/${caseId}/evidence`} className="inline-flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200">
        <ArrowLeft className="h-4 w-4" aria-hidden /> Evidence list
      </Link>

      <WorkspaceHeader
        caseId={caseId}
        evidence={e}
        current={current}
        onReprocessed={() => setVersion((n) => n + 1)}
        onHistory={() => changeTab("runs")}
      />

      <div className="grid grid-cols-3 gap-3 md:grid-cols-6">
        <StatTile label="Segments" value={s?.segments ?? "—"} />
        <StatTile label="Claims" value={s?.claims ?? "—"} />
        <StatTile label="Entities" value={s?.entities ?? "—"} />
        <StatTile label="Relationships" value={s?.relationships ?? "—"} />
        <StatTile label="Potential inconsistencies" value={s?.contradictions ?? "—"} tone={s?.contradictions ? "amber" : "neutral"} />
        <StatTile label="Awaiting review" value={s?.awaiting_review ?? "—"} tone={s?.awaiting_review ? "amber" : "neutral"} />
      </div>

      {e.processing_status !== "completed" && !current && (
        <Card className="p-4 text-sm text-slate-300">
          {e.processing_status === "processing" ? (
            <span className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Processing… this page updates when the
              extraction is ready.
            </span>
          ) : e.processing_status === "failed" ? (
            <span className="text-failed">
              Processing failed{errorCodeLabel(e.processing_error_code) ? `: ${errorCodeLabel(e.processing_error_code)}` : ""}.{" "}
              {e.processing_error}
            </span>
          ) : (
            "This file has not been processed yet. Process it from the evidence list or with the button above."
          )}
        </Card>
      )}

      <Tabs
        label="Evidence workspace sections"
        tabs={WORKSPACE_TABS.map((t) => ({
          ...t,
          count: t.id === "claims" ? claims.data?.total : t.id === "runs" ? runs.data?.total : undefined,
        }))}
        active={tab}
        onChange={changeTab}
      />

      {tab === "overview" && <OverviewTab evidence={e} current={current} claims={claimList} onShowSource={showSource} caseId={caseId} />}
      {tab === "preview" && (
        <section aria-label="Original preview">
          <LayerNote icon={<FileText className="h-3.5 w-3.5" aria-hidden />} title="Original evidence">
            The uploaded file, unaltered. Overlays mark where extracted segments came from.
          </LayerNote>
          {segments.loading && !segments.data ? <LoadingState /> : <Viewer evidence={e} props={viewerProps} />}
          {segments.data?.capped && (
            <p className="mt-2 text-xs text-slate-500">Showing the first {MAX_SEGMENTS} segments.</p>
          )}
        </section>
      )}
      {tab === "content" && (
        <section aria-label="Extracted content">
          <LayerNote icon={<Layers className="h-3.5 w-3.5" aria-hidden />} title="Extracted content">
            What the extractor read from the file, segment by segment, with locators. Never edited.
          </LayerNote>
          <ExtractionViewer caseId={caseId} evidenceId={evidenceId} refreshToken={version} />
        </section>
      )}
      {tab === "claims" && (
        <section aria-label="Claims">
          <LayerNote icon={<Quote className="h-3.5 w-3.5" aria-hidden />} title="Machine claims">
            Statements derived from the extracted content. Each quotes its source and is unverified until reviewed.
          </LayerNote>
          {claims.error && <ErrorState message={claims.error} onRetry={claims.reload} />}
          {claims.data?.total === 0 && <EmptyState title="No claims for this file">Run the case analysis after processing.</EmptyState>}
          <div className="space-y-3">
            {claimList.map((c) => (
              <ClaimCard
                key={c.id}
                caseId={caseId}
                claim={c}
                onShowSource={showSource}
                onChanged={(u) =>
                  claims.data && claims.setData({ ...claims.data, items: claims.data.items.map((x) => (x.id === u.id ? { ...x, ...u } : x)) })
                }
              />
            ))}
          </div>
        </section>
      )}
      {tab === "entities" && <EntitiesTab caseId={caseId} claims={claimList} />}
      {tab === "relationships" && <RelationshipsTab caseId={caseId} evidenceId={evidenceId} version={version + analysisVersion} />}
      {tab === "processing" && <ProcessingTab current={current} />}
      {tab === "runs" && <RunsTab runs={runs.data?.items ?? []} />}
    </div>
  );
}

/** 404: the item is not in this case (wrong link, deleted, or another case's id). */
function EvidenceNotFound({ caseId }: { caseId: string }) {
  return (
    <Card className="p-6" as="section">
      <div role="alert" className="flex items-start gap-3">
        <FileQuestion className="mt-0.5 h-5 w-5 shrink-0 text-slate-400" aria-hidden />
        <div>
          <h2 className="text-base font-semibold text-slate-100">Evidence item not found</h2>
          <p className="mt-1 max-w-2xl text-sm text-slate-400">
            This evidence item could not be found in this case. It may have been deleted, or the link
            may be incorrect or belong to a different case.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link href={`/cases/${caseId}/evidence`} className={BUTTON_PRIMARY}>
              <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Back to the evidence library
            </Link>
            <Link href={`/cases/${caseId}`} className={BUTTON}>
              Case overview
            </Link>
          </div>
        </div>
      </div>
    </Card>
  );
}

function LayerNote({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <p className="mb-3 flex items-center gap-2 text-xs text-slate-400">
      <span className="inline-flex items-center gap-1 rounded bg-navy-800 px-2 py-0.5 font-medium text-slate-200">
        {icon}
        {title}
      </span>
      {children}
    </p>
  );
}

function Viewer({ evidence, props }: { evidence: Evidence; props: ViewerProps }) {
  // PDFs, images and recordings can be previewed before extraction; tables and emails
  // are shown from their extracted structure.
  const structural = evidence.evidence_type === "tabular" || evidence.evidence_type === "email";
  if (structural && props.segments.length === 0) {
    return <EmptyState title="No extracted content to show">Process this file to view it here.</EmptyState>;
  }
  switch (evidence.evidence_type) {
    case "document":
      return <PdfViewer {...props} />;
    case "image":
      return <ImageViewer {...props} />;
    case "audio":
      return <AudioViewer {...props} />;
    case "tabular":
      return <TableViewer {...props} />;
    case "email":
      return <EmailViewer {...props} />;
    case "video":
      return <VideoViewer {...props} />;
    default:
      return <EmptyState title="No preview for this file type" />;
  }
}

function WorkspaceHeader({
  caseId,
  evidence: e,
  current,
  onReprocessed,
  onHistory,
}: {
  caseId: string;
  evidence: Evidence;
  current: Extraction | null;
  onReprocessed: () => void;
  onHistory: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [model, setModel] = useState("");
  // Video soundtracks are transcribed with the same speech models as audio files.
  const isAudio = e.evidence_type === "audio" || e.evidence_type === "video";
  const models = useApi((signal) => (isAudio ? listAudioModels(signal) : Promise.resolve(null)), [isAudio]);
  const meta = current?.doc_metadata ?? {};
  const engine = current
    ? `${current.extractor} v${current.extractor_version}${typeof meta.model === "string" ? ` · model ${meta.model}` : ""}`
    : "—";

  async function reprocess() {
    setBusy(true);
    setError(null);
    try {
      const res = await processEvidence(caseId, e.id, {
        force: e.processing_status === "completed",
        audioModel: isAudio && model ? model : undefined,
      });
      if (res.queued.length === 0) setError(`Not queued (${res.skipped[0]?.reason ?? "skipped"}).`);
      onReprocessed();
    } catch (err) {
      setError(errorText(err, "Processing could not be started."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate text-xl font-semibold text-slate-100">{e.original_filename}</h2>
            <Badge tone={STATUS_TONE[e.processing_status]}>{e.processing_status}</Badge>
            {current?.outcome && current.outcome !== "ok" && <Badge tone="amber">{outcomeLabel(current.outcome)}</Badge>}
          </div>
          <dl className="mt-3 grid grid-cols-2 gap-x-8 gap-y-1.5 text-xs sm:grid-cols-4">
            <Fact label="Type">
              {e.evidence_type} · {e.mime_type}
            </Fact>
            <Fact label="Size">{formatBytes(e.byte_size)}</Fact>
            <Fact label="Uploaded">{formatDateTime(e.uploaded_at)}</Fact>
            <Fact label="Current run">{current ? `Run ${current.run_number}` : "none"}</Fact>
            <Fact label="Engine / model">{engine}</Fact>
            <Fact label="Processing time">{current ? formatDurationMs(current.duration_ms) : "—"}</Fact>
            <div className="col-span-2 min-w-0">
              <dt className="text-slate-500">SHA-256 (content fingerprint, not an authenticity check)</dt>
              <dd className="flex items-center gap-1.5 font-mono text-[11px] text-slate-300">
                <span className="truncate" title={e.sha256}>
                  {e.sha256}
                </span>
                <button
                  type="button"
                  aria-label="Copy SHA-256"
                  className="rounded p-0.5 text-slate-500 hover:text-slate-200"
                  onClick={() => {
                    void navigator.clipboard?.writeText(e.sha256).then(() => {
                      setCopied(true);
                      setTimeout(() => setCopied(false), 1500);
                    });
                  }}
                >
                  <Copy className="h-3 w-3" aria-hidden />
                </button>
                {copied && <span className="font-sans text-processed">copied</span>}
              </dd>
            </div>
          </dl>
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="flex flex-wrap justify-end gap-1.5">
            {isAudio && models.data && (
              <select
                value={model}
                onChange={(ev) => setModel(ev.target.value)}
                className={`${INPUT} w-auto py-1 text-xs`}
                aria-label="Speech model for the next run"
              >
                <option value="">Default model ({models.data.default})</option>
                {models.data.items.map((m) => (
                  <option key={m.name} value={m.name} disabled={!m.available}>
                    {m.name}
                    {m.available ? "" : " (not on disk)"}
                  </option>
                ))}
              </select>
            )}
            <button type="button" className={BUTTON_PRIMARY} disabled={busy || e.processing_status === "processing"} onClick={() => void reprocess()}>
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <RotateCcw className="h-3.5 w-3.5" aria-hidden />}
              {e.processing_status === "completed" ? "Reprocess (new run)" : e.processing_status === "failed" ? "Retry" : "Process"}
            </button>
            <a href={evidenceDownloadUrl(caseId, e.id)} className={BUTTON}>
              <Download className="h-3.5 w-3.5" aria-hidden /> Download original
            </a>
            <button type="button" className={BUTTON} onClick={onHistory}>
              <History className="h-3.5 w-3.5" aria-hidden /> History
            </button>
          </div>
          {isAudio && models.data && !models.data.default_available && (
            <p className="text-xs text-failed">The default speech model is not on disk.</p>
          )}
          {error && (
            <p role="alert" className="text-xs text-failed">
              {error}
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}

function OverviewTab({
  caseId,
  evidence: e,
  current,
  claims,
  onShowSource,
}: {
  caseId: string;
  evidence: Evidence;
  current: Extraction | null;
  claims: Claim[];
  onShowSource: (c: Claim) => void;
}) {
  const conflicted = claims.filter((c) => c.contradiction_count > 0);
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="p-4 lg:col-span-1">
        <p className="text-sm font-medium text-slate-200">Three separate layers</p>
        <ol className="mt-2 space-y-2 text-xs text-slate-400">
          <li>
            <span className="font-medium text-slate-200">1. Original evidence</span> — the uploaded file, stored by
            its SHA-256 and never modified.
          </li>
          <li>
            <span className="font-medium text-slate-200">2. Extracted content</span> — text and structure read
            mechanically from the file{current ? ` (run ${current.run_number}, ${current.extractor})` : ""}. Each
            segment keeps its page, region, row or timestamp.
          </li>
          <li>
            <span className="font-medium text-slate-200">3. Machine claims</span> — statements derived from the
            extracted content ({claims[0] ? methodLabel(claims[0].extraction_method) : "after analysis"}). Each quotes
            its segment exactly and remains unverified until a person reviews it.
          </li>
        </ol>
        {current && current.warnings.length > 0 && (
          <div className="mt-4">
            <p className="text-xs font-medium text-slate-300">Extraction warnings</p>
            <ul className="mt-1 space-y-1 text-xs text-slate-400">
              {current.warnings.map((w, i) => (
                <li key={`${w.code}-${i}`}>
                  <span className="font-mono text-slate-500">{w.code}</span> {w.message}
                </li>
              ))}
            </ul>
          </div>
        )}
        {e.processing_error && e.processing_status === "failed" && (
          <p className="mt-3 text-xs text-failed">Latest attempt failed: {e.processing_error}</p>
        )}
      </Card>
      <div className="space-y-3 lg:col-span-2">
        <p className="text-sm font-medium text-slate-200">
          {conflicted.length > 0 ? "Claims involved in potential inconsistencies" : "Recent claims"}
        </p>
        {claims.length === 0 && <EmptyState title="No claims yet">Run the case analysis after processing.</EmptyState>}
        {(conflicted.length > 0 ? conflicted : claims).slice(0, 4).map((c) => (
          <ClaimCard key={c.id} caseId={caseId} claim={c} onShowSource={onShowSource} compact />
        ))}
      </div>
    </div>
  );
}

function EntitiesTab({ caseId, claims }: { caseId: string; claims: Claim[] }) {
  const rows = useMemo(() => {
    const map = new Map<string, { id: string; name: string; type: string; mentions: Set<string>; count: number }>();
    for (const c of claims) {
      for (const m of c.entities) {
        const row = map.get(m.entity_id) ?? { id: m.entity_id, name: m.display_name, type: m.entity_type, mentions: new Set(), count: 0 };
        row.mentions.add(m.mention_text);
        row.count += 1;
        map.set(m.entity_id, row);
      }
    }
    return [...map.values()].sort((a, b) => b.count - a.count);
  }, [claims]);
  if (rows.length === 0) return <EmptyState title="No entities found in this file" />;
  return (
    <Card>
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-navy-800 text-left text-xs text-slate-500">
            <th className="px-3 py-2 font-medium">Entity</th>
            <th className="px-3 py-2 font-medium">Type</th>
            <th className="px-3 py-2 font-medium">Written in this file as</th>
            <th className="px-3 py-2 font-medium">Claims</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-b border-navy-800/60">
              <td className="px-3 py-2">
                <Link href={`/cases/${caseId}/entities?focus=${r.id}`} className="text-slate-100 hover:underline">
                  {r.name}
                </Link>
              </td>
              <td className="px-3 py-2 text-slate-400">{r.type}</td>
              <td className="px-3 py-2 font-mono text-xs text-slate-300">{[...r.mentions].join(", ")}</td>
              <td className="px-3 py-2 tabular-nums text-slate-300">{r.count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function RelationshipsTab({ caseId, evidenceId, version }: { caseId: string; evidenceId: string; version: number }) {
  const { data, error, loading, reload } = useApi((signal) => listRelationships(caseId, { evidenceId }, signal), [caseId, evidenceId, version]);
  if (loading && !data) return <LoadingState />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data || data.total === 0) return <EmptyState title="No cross-evidence relationships for this file" />;
  return (
    <ul className="space-y-2">
      {data.items.map((r) => {
        const other = r.source_claim.evidence_id === evidenceId ? r.target_claim : r.source_claim;
        const own = other === r.target_claim ? r.source_claim : r.target_claim;
        return (
          <li key={r.id}>
            <Card className="p-3 text-sm">
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge tone={r.relation_type === "potentially_conflicts_with" ? "amber" : "neutral"}>
                  {r.relation_type.replace(/_/g, " ")}
                </Badge>
                {r.via_entity_name && <span className="text-xs text-slate-400">via {r.via_entity_name}</span>}
                <span className="text-xs text-slate-500">{r.origin}</span>
              </div>
              <p className="mt-1 text-xs text-slate-400">{r.rationale}</p>
              <div className="mt-2 grid gap-2 md:grid-cols-2">
                <div className="rounded border border-navy-800 bg-navy-950/60 p-2">
                  <p className="text-[11px] text-slate-500">This file · {sourceLabel(own.locator)}</p>
                  <p className="font-mono text-xs text-slate-200">{own.quote}</p>
                </div>
                <div className="rounded border border-navy-800 bg-navy-950/60 p-2">
                  <p className="text-[11px] text-slate-500">
                    <Link href={`/cases/${caseId}/evidence/${other.evidence_id}`} className="hover:underline">
                      {other.evidence_name}
                    </Link>{" "}
                    · {sourceLabel(other.locator)}
                  </p>
                  <p className="font-mono text-xs text-slate-200">{other.quote}</p>
                </div>
              </div>
            </Card>
          </li>
        );
      })}
    </ul>
  );
}

function ProcessingTab({ current }: { current: Extraction | null }) {
  if (!current) return <EmptyState title="No completed extraction yet" />;
  const m = current.doc_metadata;
  const audioKeys = ["model", "device", "compute_type", "language", "language_probability", "duration_seconds", "word_timestamps", "low_word_probability_threshold", "initial_prompt_used", "transcription"];
  const isAudio = typeof m.transcription === "string";
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="p-4">
        <p className="text-sm font-medium text-slate-200">Run {current.run_number}</p>
        <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
          <Fact label="Extractor">
            {current.extractor} v{current.extractor_version}
          </Fact>
          <Fact label="Outcome">{current.outcome ? outcomeLabel(current.outcome) : "—"}</Fact>
          <Fact label="Started">{formatDateTime(current.started_at)}</Fact>
          <Fact label="Recorded">{formatDateTime(current.recorded_at)}</Fact>
          <Fact label="Duration">{formatDurationMs(current.duration_ms)}</Fact>
          <Fact label="Segments">{current.segment_count}</Fact>
          <Fact label="Source SHA-256 read">
            <span className="font-mono">{current.source_sha256.slice(0, 16)}…</span>
          </Fact>
        </dl>
        {isAudio && (
          <>
            <p className="mt-4 text-sm font-medium text-slate-200">Speech recognition settings</p>
            <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
              {audioKeys
                .filter((k) => m[k] !== undefined && m[k] !== null)
                .map((k) => (
                  <Fact key={k} label={k.replace(/_/g, " ")}>
                    {String(m[k])}
                  </Fact>
                ))}
            </dl>
          </>
        )}
      </Card>
      <Card className="p-4">
        <p className="text-sm font-medium text-slate-200">Warnings ({current.warnings.length})</p>
        <ul className="mt-2 space-y-1 text-xs text-slate-300">
          {current.warnings.map((w, i) => (
            <li key={`${w.code}-${i}`}>
              <span className="mr-1 rounded bg-navy-800 px-1.5 py-0.5 font-mono text-slate-400">{w.code}</span>
              {w.message}
            </li>
          ))}
          {current.warnings.length === 0 && <li className="text-slate-500">None.</li>}
        </ul>
        <details className="mt-4 text-xs text-slate-500">
          <summary className="cursor-pointer text-slate-400">All run metadata</summary>
          <pre className="mt-1 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded bg-navy-950 p-2 text-[11px]">
            {JSON.stringify(m, null, 2)}
          </pre>
        </details>
      </Card>
    </div>
  );
}

function RunsTab({ runs }: { runs: Extraction[] }) {
  if (runs.length === 0) return <EmptyState title="No runs yet" />;
  return (
    <Card>
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-navy-800 text-left text-xs text-slate-500">
            <th className="px-3 py-2 font-medium">Run</th>
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-3 py-2 font-medium">Extractor</th>
            <th className="px-3 py-2 font-medium">Recorded</th>
            <th className="px-3 py-2 font-medium">Duration</th>
            <th className="px-3 py-2 font-medium">Segments</th>
            <th className="px-3 py-2 font-medium">Result</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id} className="border-b border-navy-800/60 align-top">
              <td className="px-3 py-2 text-slate-100">
                {r.run_number} {r.is_current && <Badge tone="green">current</Badge>}
              </td>
              <td className="px-3 py-2">
                <Badge tone={r.run_status === "completed" ? "green" : "red"}>{r.run_status}</Badge>
              </td>
              <td className="px-3 py-2 text-xs text-slate-300">
                {r.extractor} v{r.extractor_version}
                {typeof r.doc_metadata.model === "string" ? ` · ${r.doc_metadata.model}` : ""}
              </td>
              <td className="px-3 py-2 text-xs text-slate-400">{formatDateTime(r.recorded_at)}</td>
              <td className="px-3 py-2 text-xs text-slate-400">{formatDurationMs(r.duration_ms)}</td>
              <td className="px-3 py-2 tabular-nums text-slate-300">{r.segment_count}</td>
              <td className="px-3 py-2 text-xs text-slate-400">
                {r.run_status === "failed" ? (
                  <span className="text-failed">
                    {errorCodeLabel(r.error_code) ?? r.error_code}: {r.error_message}
                  </span>
                ) : r.outcome ? (
                  outcomeLabel(r.outcome)
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="px-3 py-2 text-xs text-slate-500">
        Runs are append-only. Reprocessing adds a run; earlier runs, their segments and any claims anchored
        to them are kept.
      </p>
    </Card>
  );
}
