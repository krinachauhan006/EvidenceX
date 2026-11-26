"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";
import {
  Braces,
  Download,
  Eye,
  FileBarChart,
  FileText,
  Loader2,
  Network,
  Share2,
} from "lucide-react";
import { createReport, graphExport, listReports, reportPdf } from "@/lib/api/phase2";
import { saveBlob } from "@/lib/api/client";
import type { Report } from "@/lib/types/phase2";
import { hasRole } from "@/lib/types/case";
import { formatBytes, formatDateTime } from "@/lib/format";
import { useCaseContext } from "@/components/cases/case-shell";
import {
  Badge,
  BUTTON,
  BUTTON_SOLID,
  Card,
  EmptyState,
  ErrorState,
  InfoTip,
  SectionHeader,
  Skeleton,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { errorText, useApi } from "@/hooks/use-api";

export default function ReportsPage() {
  const { caseItem, role } = useCaseContext();
  const caseId = caseItem.id;
  const notify = useToast();
  const canCreate = hasRole(role, "reviewer");
  const [version, setVersion] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [preview, setPreview] = useState<Report | null>(null);
  const list = useApi((signal) => listReports(caseId, signal), [caseId, version], "Could not load reports.");

  useEffect(() => {
    if (!preview && list.data?.items.length) setPreview(list.data.items[0]);
  }, [list.data, preview]);

  async function generate(kind: "investigation" | "graph") {
    setBusy(kind);
    try {
      const r = await createReport(caseId, { kind });
      notify("success", `${kind === "graph" ? "Knowledge-graph" : "Investigation"} report v${r.version} ready`, `${r.page_count} page(s) · ${formatBytes(r.byte_size)}`);
      setPreview(r);
      setVersion((n) => n + 1);
    } catch (err) {
      notify("error", "The report could not be generated", errorText(err, ""));
    } finally {
      setBusy(null);
    }
  }

  async function download(r: Report) {
    setBusy(`dl-${r.id}`);
    try {
      saveBlob(await reportPdf(caseId, r.id), `evidencex-${r.kind}-report-v${r.version}.pdf`);
    } catch (err) {
      notify("error", "Download failed", errorText(err, ""));
    } finally {
      setBusy(null);
    }
  }

  async function exportGraph(format: "json" | "graphml") {
    setBusy(format);
    try {
      saveBlob(await graphExport(caseId, format), `evidencex-graph.${format}`);
      notify("success", `Graph exported as ${format.toUpperCase()}`);
    } catch (err) {
      notify("error", "Export failed", errorText(err, ""));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <SectionHeader
        title="Reports & exports"
        description="Generated PDFs are stored with a version number and a SHA-256 hash of their content. They summarise what the evidence says and where accounts appear to differ; they do not determine guilt, deception or authenticity."
      />
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <ActionCard
          icon={<FileText className="h-5 w-5" aria-hidden />}
          title="Investigation report"
          text="Summary, scope, methods and limits, events and timeline, possible inconsistencies with alternatives, gaps, and the review trail."
          action={canCreate ? () => void generate("investigation") : undefined}
          busy={busy === "investigation"}
          label="Generate PDF"
        />
        <ActionCard
          icon={<Network className="h-5 w-5" aria-hidden />}
          title="Knowledge-graph report"
          text="The case graph drawn as a page, with a legend and the list of nodes and links it shows."
          action={canCreate ? () => void generate("graph") : undefined}
          busy={busy === "graph"}
          label="Generate PDF"
        />
        <ActionCard
          icon={<Braces className="h-5 w-5" aria-hidden />}
          title="Graph as JSON"
          text="Nodes and edges with their source references, for scripts and other tools."
          action={() => void exportGraph("json")}
          busy={busy === "json"}
          label="Download JSON"
        />
        <ActionCard
          icon={<Share2 className="h-5 w-5" aria-hidden />}
          title="Graph as GraphML"
          text="Opens in Gephi, yEd, Cytoscape and other graph tools."
          action={() => void exportGraph("graphml")}
          busy={busy === "graphml"}
          label="Download GraphML"
        />
      </div>
      {!canCreate && (
        <p className="mt-2 text-xs text-slate-500">Generating reports needs the reviewer role or higher. You can still view and download existing ones.</p>
      )}

      <div className="mt-6 grid gap-4 xl:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <div>
          <p className="mb-2 text-sm font-medium text-slate-200">Generated reports</p>
          {list.loading && !list.data && <Skeleton rows={3} />}
          {list.error && <ErrorState message={list.error} onRetry={list.reload} />}
          {list.data && list.data.items.length === 0 && (
            <EmptyState title="No reports yet" icon={<FileBarChart className="h-5 w-5" aria-hidden />}>
              Generate one above. Each new report gets the next version number; older versions are kept.
            </EmptyState>
          )}
          <ul className="space-y-2">
            {list.data?.items.map((r) => (
              <li key={r.id}>
                <div
                  className={clsx(
                    "rounded-xl border p-3 text-sm transition-colors",
                    preview?.id === r.id ? "border-sky-500/50 bg-sky-500/5" : "border-white/[0.06] bg-navy-900/70 hover:border-navy-600",
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-slate-100">
                      {r.kind === "graph" ? "Knowledge graph" : "Investigation"} · v{r.version}
                    </span>
                    <Badge>{r.page_count} p.</Badge>
                  </div>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {formatDateTime(r.created_at)} · {r.created_by ?? "unknown"} · {formatBytes(r.byte_size)}
                  </p>
                  <p className="mt-0.5 flex items-center gap-1 font-mono text-[11px] text-slate-500" title={r.content_sha256}>
                    sha256 {r.content_sha256.slice(0, 16)}…
                    <InfoTip text="The hash identifies this exact file. Anyone can recompute it to check the download was not altered after generation. It says nothing about whether the evidence is accurate." />
                  </p>
                  <div className="mt-2 flex gap-1.5">
                    <button type="button" className={BUTTON} onClick={() => setPreview(r)}>
                      <Eye className="h-3 w-3" aria-hidden /> Preview
                    </button>
                    <button type="button" className={BUTTON} disabled={busy === `dl-${r.id}`} onClick={() => void download(r)}>
                      {busy === `dl-${r.id}` ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> : <Download className="h-3 w-3" aria-hidden />}
                      PDF
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <div>{preview && <PdfPreview caseId={caseId} report={preview} />}</div>
      </div>
    </div>
  );
}

function ActionCard({
  icon,
  title,
  text,
  action,
  busy,
  label,
}: {
  icon: React.ReactNode;
  title: string;
  text: string;
  action?: () => void;
  busy: boolean;
  label: string;
}) {
  return (
    <Card className="evx-card-hover flex flex-col p-4">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-sky-500/30 bg-sky-500/10 text-sky-300">{icon}</div>
      <p className="mt-3 font-medium text-slate-100">{title}</p>
      <p className="mt-1 flex-1 text-xs text-slate-400">{text}</p>
      {action && (
        <button type="button" className={`${BUTTON_SOLID} mt-3 text-xs`} onClick={action} disabled={busy}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
          {busy ? "Working…" : label}
        </button>
      )}
    </Card>
  );
}

/** The stored PDF, fetched with the session and shown from a local object URL. */
function PdfPreview({ caseId, report }: { caseId: string; report: Report }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    let made: string | null = null;
    setUrl(null);
    setError(null);
    reportPdf(caseId, report.id, controller.signal)
      .then((b) => {
        made = URL.createObjectURL(b);
        setUrl(made);
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setError(errorText(err, "The preview could not be loaded."));
      });
    return () => {
      controller.abort();
      if (made) URL.revokeObjectURL(made);
    };
  }, [caseId, report.id]);
  return (
    <Card className="overflow-hidden">
      <p className="border-b border-navy-800 px-3 py-2 text-xs text-slate-400">
        Preview · {report.title} · v{report.version}
      </p>
      {error && <div className="p-3"><ErrorState message={error} /></div>}
      {!url && !error && (
        <div className="flex h-[40rem] items-center justify-center text-sm text-slate-500">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden /> Loading PDF…
        </div>
      )}
      {url && <iframe title={`Report ${report.title}`} src={url} className="h-[44rem] w-full bg-white" />}
    </Card>
  );
}
