"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Download,
  Eye,
  History,
  PanelsTopLeft,
  Play,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { evidenceDownloadUrl } from "@/lib/api/evidence";
import { formatBytes, formatDateTime } from "@/lib/format";
import type { Evidence } from "@/lib/types/evidence";
import type { ProcessingItem } from "@/lib/types/processing";
import { ExtractionViewer } from "@/components/evidence/extraction-viewer";
import { FileTypeIcon } from "@/components/evidence/file-type-icon";
import {
  awaitingWorker,
  errorCodeLabel,
  outcomeLabel,
} from "@/components/evidence/processing-labels";
import { ProcessingStatusBadge } from "@/components/evidence/processing-status-badge";

interface Props {
  caseId: string;
  evidence: Evidence;
  /** Live processing info for this item (undefined until the first status load). */
  item: ProcessingItem | undefined;
  /** Accepted by the server but not started yet. */
  queued: boolean;
  /** Bumped when processing for this item settles; reloads the open viewer. */
  viewerRefreshToken: number;
  /** A process/retry request for this item is in flight. */
  actionBusy: boolean;
  confirmingDelete: boolean;
  deleting: boolean;
  onProcess: () => void;
  onRetry: () => void;
  onReprocess: () => void;
  onAskDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
}

const ACTION_BUTTON =
  "inline-flex items-center gap-1 rounded-md border border-navy-700 px-2.5 py-1.5 text-xs text-slate-200 hover:bg-navy-800 disabled:cursor-not-allowed disabled:opacity-50";

export function EvidenceRow({
  caseId,
  evidence: e,
  item,
  queued,
  viewerRefreshToken,
  actionBusy,
  confirmingDelete,
  deleting,
  onProcess,
  onRetry,
  onReprocess,
  onAskDelete,
  onCancelDelete,
  onConfirmDelete,
}: Props) {
  const [viewerOpen, setViewerOpen] = useState(false);
  const [confirmingReprocess, setConfirmingReprocess] = useState(false);

  // The status feed is fresher than the evidence list while work is running.
  const status = item?.status ?? e.processing_status;
  const outcome = item?.outcome ?? null;
  const extractorAvailable = item ? item.extractor_available : null;
  const hasCurrent = item ? item.run_number !== null : false;
  const attempts = item?.attempts ?? e.processing_attempts;
  const errorCode = item?.error_code ?? e.processing_error_code;
  const busy = status === "processing" || queued || actionBusy;
  // This server leaves the file type to the separate processing worker.
  const external = item?.external_worker === true;
  const waitingForWorker = awaitingWorker(status, external, errorCode);

  // Process/retry/re-process would only be refused for external file types, so the
  // buttons are not offered; the worker handles those items.
  const canProcess = status === "pending" && extractorAvailable === true && !external && !busy;
  const canRetry = status === "failed" && !external && !busy;
  const canReprocess =
    status === "completed" && extractorAvailable !== false && !external && !busy;
  const canView = hasCurrent || attempts > 0;

  return (
    <li className="px-5 py-3">
      <div className="flex items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <span className="text-slate-400">
            <FileTypeIcon type={e.evidence_type} />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <p className="truncate font-medium text-slate-100">{e.original_filename}</p>
              <ProcessingStatusBadge
                status={status}
                outcome={outcome}
                queued={queued}
                extractorAvailable={extractorAvailable}
                awaitingWorker={waitingForWorker}
              />
            </div>
            <p className="mt-0.5 text-xs text-slate-500">
              {e.evidence_type} · {formatBytes(e.byte_size)} · {formatDateTime(e.uploaded_at)}
              {hasCurrent && item && (
                <>
                  {" · "}
                  {item.segment_count} segment{item.segment_count === 1 ? "" : "s"} · run{" "}
                  {item.run_number}
                  {outcome && outcome !== "ok" ? ` · ${outcomeLabel(outcome)}` : ""}
                </>
              )}
            </p>
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center justify-end gap-1">
          {canProcess && (
            <button type="button" onClick={onProcess} className={ACTION_BUTTON}>
              <Play className="h-3.5 w-3.5" aria-hidden />
              Process
            </button>
          )}
          {canRetry && (
            <button type="button" onClick={onRetry} className={ACTION_BUTTON}>
              <RotateCcw className="h-3.5 w-3.5" aria-hidden />
              Retry
            </button>
          )}
          {canReprocess && (
            <button
              type="button"
              onClick={() => setConfirmingReprocess(true)}
              className={ACTION_BUTTON}
            >
              <RotateCcw className="h-3.5 w-3.5" aria-hidden />
              Re-process
            </button>
          )}
          <Link
            href={`/cases/${caseId}/evidence/${e.id}`}
            className="inline-flex items-center gap-1 rounded-md border border-navy-600 bg-navy-800 px-2.5 py-1.5 text-xs font-medium text-slate-100 hover:bg-navy-700"
          >
            <PanelsTopLeft className="h-3.5 w-3.5" aria-hidden />
            Open workspace
          </Link>
          {canView && (
            <button
              type="button"
              onClick={() => setViewerOpen((v) => !v)}
              aria-expanded={viewerOpen}
              className={ACTION_BUTTON}
            >
              {hasCurrent ? (
                <Eye className="h-3.5 w-3.5" aria-hidden />
              ) : (
                <History className="h-3.5 w-3.5" aria-hidden />
              )}
              {viewerOpen ? "Hide" : hasCurrent ? "View extraction" : "View history"}
            </button>
          )}
          <a
            href={evidenceDownloadUrl(caseId, e.id)}
            className="inline-flex items-center gap-1 rounded-md border border-navy-700 px-2.5 py-1.5 text-xs text-slate-200 hover:bg-navy-800"
          >
            <Download className="h-3.5 w-3.5" aria-hidden />
            Download
          </a>
          <button
            onClick={onAskDelete}
            className="inline-flex items-center gap-1 rounded-md border border-failed/40 px-2.5 py-1.5 text-xs text-failed hover:bg-failed/10"
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden />
            Delete
          </button>
        </div>
      </div>

      {waitingForWorker && (
        <div role="status" className="mt-2 rounded-md border border-navy-700 bg-navy-900 px-3 py-2">
          <p className="text-xs font-medium text-unresolved">Waiting for the processing worker</p>
          <p className="mt-0.5 text-xs text-slate-400">
            This file type (OCR, speech or video) is processed by a separate processing worker,
            not by this server. It is picked up automatically; refresh the page to see the
            result.
          </p>
        </div>
      )}

      {status === "failed" && !waitingForWorker && (
        <div role="alert" className="mt-2 rounded-md border border-failed/30 bg-failed/10 px-3 py-2">
          <p className="text-xs font-medium text-failed">
            Processing failed
            {errorCodeLabel(errorCode) ? `: ${errorCodeLabel(errorCode)}` : ""}
          </p>
          {e.processing_error && (
            <p className="mt-0.5 whitespace-pre-wrap break-words text-xs text-slate-300">
              {e.processing_error}
            </p>
          )}
          {hasCurrent && (
            <p className="mt-0.5 text-xs text-slate-500">
              Results from an earlier successful run are still available.
            </p>
          )}
        </div>
      )}

      {confirmingReprocess && (
        <div
          role="alertdialog"
          aria-label="Confirm re-process"
          className="mt-3 rounded-md border border-navy-700 bg-charcoal-800 p-3"
        >
          <p className="text-sm text-slate-200">
            Re-process <strong>{e.original_filename}</strong>? A new extraction run will be
            created and become the current run. Earlier runs are kept and stay viewable.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={() => {
                setConfirmingReprocess(false);
                onReprocess();
              }}
              className="rounded-md bg-navy-700 px-3 py-1.5 text-xs font-medium text-slate-100 hover:bg-navy-600"
            >
              Create new run
            </button>
            <button
              type="button"
              onClick={() => setConfirmingReprocess(false)}
              className="rounded-md border border-navy-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-navy-800"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {confirmingDelete && (
        <div
          role="alertdialog"
          aria-label="Confirm delete evidence"
          className="mt-3 rounded-md border border-failed/40 bg-charcoal-800 p-3"
        >
          <p className="text-sm text-slate-200">
            Permanently delete <strong>{e.original_filename}</strong>? This removes the file and
            cannot be undone.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              onClick={onConfirmDelete}
              disabled={deleting}
              className="rounded-md bg-failed px-3 py-1.5 text-xs font-medium text-navy-950 hover:opacity-90 disabled:opacity-50"
            >
              {deleting ? "Deleting…" : "Yes, delete"}
            </button>
            <button
              onClick={onCancelDelete}
              disabled={deleting}
              className="rounded-md border border-navy-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-navy-800"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {viewerOpen && (
        <ExtractionViewer
          caseId={caseId}
          evidenceId={e.id}
          refreshToken={viewerRefreshToken}
          onClose={() => setViewerOpen(false)}
        />
      )}
    </li>
  );
}
