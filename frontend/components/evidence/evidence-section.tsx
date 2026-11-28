"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { UploadCloud, Loader2, AlertTriangle, X } from "lucide-react";
import { ApiError } from "@/lib/api/client";
import {
  ACCEPTED_EXTENSIONS,
  ACCEPTED_LABEL,
  deleteEvidence,
  listEvidence,
  uploadEvidence,
} from "@/lib/api/evidence";
import { processEvidence, processPending, retryEvidence } from "@/lib/api/processing";
import type { Evidence } from "@/lib/types/evidence";
import type { ProcessAccepted, ProcessingItem } from "@/lib/types/processing";
import { useProcessingPoll } from "@/hooks/use-processing-poll";
import { useBrowserProcessing } from "@/hooks/use-browser-processing";
import { EvidenceRow } from "@/components/evidence/evidence-row";
import { FileTypeIcon } from "@/components/evidence/file-type-icon";
import { skipReasonText } from "@/components/evidence/processing-labels";
import { ProcessingToolbar } from "@/components/evidence/processing-toolbar";
import { useToast } from "@/components/ui/toast";

const MAX_MB = 25; // Mirrors the backend default MAX_UPLOAD_SIZE_MB.
const MAX_VIDEO_MB = 200; // Mirrors the backend default MAX_VIDEO_UPLOAD_MB.
const VIDEO_EXT = new Set([".mp4", ".mov", ".webm"]);

interface UploadItem {
  id: string;
  name: string;
  fraction: number;
  status: "uploading" | "done" | "error";
  message?: string;
}

interface Notice {
  tone: "info" | "error";
  text: string;
}

function apiMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError && typeof err.detail === "string") return err.detail;
  return fallback;
}

export function EvidenceSection({ caseId }: { caseId: string }) {
  const [items, setItems] = useState<Evidence[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [actionBusyIds, setActionBusyIds] = useState<ReadonlySet<string>>(new Set());
  const [processAllBusy, setProcessAllBusy] = useState(false);
  const [viewerTokens, setViewerTokens] = useState<Record<string, number>>({});
  const inputRef = useRef<HTMLInputElement>(null);
  const notify = useToast();

  // `silent` refreshes the list in place without the loading state, so rows and
  // open extraction viewers do not flicker while processing finishes.
  const load = useCallback(
    async (options?: { silent?: boolean }) => {
      if (!options?.silent) {
        setLoading(true);
        setLoadError(null);
      }
      try {
        const res = await listEvidence(caseId);
        setItems(res.items);
        setLoadError(null);
      } catch {
        if (!options?.silent) {
          setLoadError("Could not load evidence. Is the backend running?");
        }
      } finally {
        if (!options?.silent) setLoading(false);
      }
    },
    [caseId],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // When items finish processing, reload the list (error text, timestamps) and
  // tell any open extraction viewer to reload its run history.
  const handleSettled = useCallback(
    (ids: string[]) => {
      void load({ silent: true });
      setViewerTokens((prev) => {
        const next = { ...prev };
        for (const id of ids) next[id] = (next[id] ?? 0) + 1;
        return next;
      });
    },
    [load],
  );

  const {
    summary,
    error: pollError,
    polling,
    queuedIds,
    markQueued,
    refresh: refreshProcessing,
  } = useProcessingPoll(caseId, { onSettled: handleSettled });

  // In-browser processing (one file at a time). After every attempt the server's status
  // is reloaded: a row shows "Completed" only once the server has saved the run.
  const browserJobs = useBrowserProcessing(caseId, (id) => {
    void refreshProcessing();
    handleSettled([id]);
  });

  const itemsById = useMemo(() => {
    const map = new Map<string, ProcessingItem>();
    for (const it of summary?.items ?? []) map.set(it.evidence_id, it);
    return map;
  }, [summary]);

  const processableCount = useMemo(
    () =>
      (summary?.items ?? []).filter(
        (it) =>
          it.status === "pending" &&
          it.extractor_available &&
          !it.external_worker &&
          !queuedIds.has(it.evidence_id),
      ).length,
    [summary, queuedIds],
  );

  const uploadOne = useCallback(
    async (file: File) => {
      const localId = `${file.name}-${Date.now()}-${Math.random()}`;
      // Client-side pre-check mirrors server rules for fast feedback; the server
      // remains the source of truth.
      const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
      if (!ACCEPTED_EXTENSIONS.includes(ext as (typeof ACCEPTED_EXTENSIONS)[number])) {
        setUploads((u) => [
          ...u,
          { id: localId, name: file.name, fraction: 0, status: "error", message: "Unsupported type" },
        ]);
        return;
      }
      if (file.size === 0) {
        setUploads((u) => [
          ...u,
          { id: localId, name: file.name, fraction: 0, status: "error", message: "File is empty" },
        ]);
        return;
      }
      const limit = VIDEO_EXT.has(ext) ? MAX_VIDEO_MB : MAX_MB;
      if (file.size > limit * 1024 * 1024) {
        setUploads((u) => [
          ...u,
          { id: localId, name: file.name, fraction: 0, status: "error", message: `Exceeds ${limit} MB` },
        ]);
        return;
      }

      setUploads((u) => [
        ...u,
        { id: localId, name: file.name, fraction: 0, status: "uploading" },
      ]);
      try {
        await uploadEvidence(caseId, file, (fraction) => {
          setUploads((u) =>
            u.map((it) => (it.id === localId ? { ...it, fraction } : it)),
          );
        });
        setUploads((u) =>
          u.map((it) =>
            it.id === localId ? { ...it, fraction: 1, status: "done" } : it,
          ),
        );
        await load();
        void refreshProcessing();
        notify("success", `Uploaded ${file.name}`, "Validated by content. Process it to extract text.");
      } catch (err) {
        const message =
          err instanceof ApiError && typeof err.detail === "string"
            ? err.detail
            : "Upload failed";
        setUploads((u) =>
          u.map((it) =>
            it.id === localId ? { ...it, status: "error", message } : it,
          ),
        );
        notify("error", `${file.name} was not uploaded`, message);
      }
    },
    [caseId, load, refreshProcessing, notify],
  );

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files) return;
      Array.from(files).forEach((f) => void uploadOne(f));
    },
    [uploadOne],
  );

  async function handleDelete(id: string) {
    setBusyId(id);
    try {
      await deleteEvidence(caseId, id);
      setConfirmId(null);
      await load();
      void refreshProcessing();
    } finally {
      setBusyId(null);
    }
  }

  // --- processing actions -----------------------------------------------------------

  const filenameOf = useCallback(
    (id: string) => items.find((e) => e.id === id)?.original_filename ?? "file",
    [items],
  );

  const handleAccepted = useCallback(
    (res: ProcessAccepted) => {
      if (res.queued.length > 0) markQueued(res.queued);
      if (res.skipped.length > 0) {
        const lines = res.skipped.map(
          (s) => `${filenameOf(s.evidence_id)}: ${skipReasonText(s.reason)}`,
        );
        setNotice({ tone: "info", text: `Not queued: ${lines.join("; ")}.` });
      } else {
        setNotice(null);
      }
    },
    [markQueued, filenameOf],
  );

  const runForItem = useCallback(
    async (id: string, request: () => Promise<ProcessAccepted>, fallback: string) => {
      setActionBusyIds((prev) => new Set(prev).add(id));
      try {
        handleAccepted(await request());
      } catch (err) {
        setNotice({ tone: "error", text: apiMessage(err, fallback) });
      } finally {
        setActionBusyIds((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
      }
    },
    [handleAccepted],
  );

  const handleProcessAll = useCallback(async () => {
    setProcessAllBusy(true);
    try {
      handleAccepted(await processPending(caseId));
    } catch (err) {
      setNotice({ tone: "error", text: apiMessage(err, "Could not start processing.") });
    } finally {
      setProcessAllBusy(false);
    }
  }, [caseId, handleAccepted]);

  return (
    <section className="mt-10">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-slate-100">Evidence</h2>
          <p className="mt-0.5 text-sm text-slate-500">
            PDF documents, images (PNG, JPG, WebP), audio (WAV, MP3, M4A), video (MP4, MOV,
            WebM), spreadsheets (CSV, XLSX) and emails (EML) attached to this case.
          </p>
        </div>
      </div>

      {/* Drop zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          handleFiles(e.dataTransfer.files);
        }}
        className={[
          "rounded-lg border-2 border-dashed p-8 text-center transition-colors",
          dragging ? "border-processed bg-processed/5" : "border-navy-700 bg-navy-900",
        ].join(" ")}
      >
        <UploadCloud className="mx-auto h-8 w-8 text-slate-500" aria-hidden />
        <p className="mt-3 text-sm text-slate-300">
          Drag &amp; drop files here, or{" "}
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="font-medium text-processed underline-offset-2 hover:underline"
          >
            browse files
          </button>
        </p>
        <p className="mt-1 text-xs text-slate-500">
          {ACCEPTED_LABEL} · up to {MAX_MB} MB each ({MAX_VIDEO_MB} MB for video)
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPTED_EXTENSIONS.join(",")}
          className="hidden"
          onChange={(e) => {
            handleFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {/* Active / recent uploads */}
      {uploads.length > 0 && (
        <ul className="mt-4 space-y-2">
          {uploads.map((u) => (
            <li
              key={u.id}
              className="flex items-center gap-3 rounded-md border border-navy-800 bg-navy-900 px-4 py-2 text-sm"
            >
              {u.status === "uploading" && (
                <Loader2 className="h-4 w-4 animate-spin text-slate-400" aria-hidden />
              )}
              {u.status === "done" && (
                <span className="h-2 w-2 rounded-full bg-processed" aria-hidden />
              )}
              {u.status === "error" && (
                <AlertTriangle className="h-4 w-4 text-inconsistency" aria-hidden />
              )}
              <span className="min-w-0 flex-1 truncate text-slate-200">{u.name}</span>
              {u.status === "uploading" && (
                <span className="text-xs text-slate-500">
                  {Math.round(u.fraction * 100)}%
                </span>
              )}
              {u.status === "error" && (
                <span className="text-xs text-inconsistency">{u.message}</span>
              )}
              {u.status === "done" && (
                <span className="text-xs text-processed">uploaded</span>
              )}
            </li>
          ))}
        </ul>
      )}

      {/* Processing overview and bulk action */}
      {!loadError && items.length > 0 && (
        <ProcessingToolbar
          counts={summary?.counts ?? null}
          processableCount={processableCount}
          submitting={processAllBusy}
          polling={polling}
          error={pollError}
          onProcessAll={() => void handleProcessAll()}
          onRefresh={() => void refreshProcessing()}
        />
      )}

      {notice && (
        <div
          role={notice.tone === "error" ? "alert" : "status"}
          className={
            notice.tone === "error"
              ? "mt-3 flex items-start justify-between gap-3 rounded-md border border-failed/40 bg-failed/10 px-3 py-2 text-sm text-failed"
              : "mt-3 flex items-start justify-between gap-3 rounded-md border border-navy-700 bg-navy-800/60 px-3 py-2 text-sm text-slate-300"
          }
        >
          <span className="min-w-0 break-words">{notice.text}</span>
          <button
            type="button"
            onClick={() => setNotice(null)}
            aria-label="Dismiss message"
            className="shrink-0 rounded p-0.5 hover:bg-navy-800"
          >
            <X className="h-3.5 w-3.5" aria-hidden />
          </button>
        </div>
      )}

      {/* Evidence list */}
      <div className="mt-6">
        {loadError && (
          <p role="alert" className="rounded-md bg-charcoal-800 p-4 text-sm text-inconsistency">
            {loadError}
          </p>
        )}

        {!loadError && loading && <p className="text-sm text-slate-500">Loading evidence…</p>}

        {!loadError && !loading && items.length === 0 && (
          <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-navy-800 py-12 text-center">
            <FileTypeIcon type="document" className="h-7 w-7 text-slate-600" />
            <p className="text-sm text-slate-400">No evidence uploaded yet.</p>
          </div>
        )}

        {!loadError && !loading && items.length > 0 && (
          <ul className="divide-y divide-navy-800 overflow-hidden rounded-lg border border-navy-800 bg-navy-900">
            {items.map((e) => (
              <EvidenceRow
                key={e.id}
                caseId={caseId}
                evidence={e}
                item={itemsById.get(e.id)}
                queued={queuedIds.has(e.id)}
                viewerRefreshToken={viewerTokens[e.id] ?? 0}
                actionBusy={actionBusyIds.has(e.id)}
                confirmingDelete={confirmId === e.id}
                deleting={busyId === e.id}
                onProcess={() =>
                  void runForItem(e.id, () => processEvidence(caseId, e.id), "Could not start processing.")
                }
                onRetry={() =>
                  void runForItem(e.id, () => retryEvidence(caseId, e.id), "Could not retry processing.")
                }
                onReprocess={() =>
                  void runForItem(
                    e.id,
                    () => processEvidence(caseId, e.id, { force: true }),
                    "Could not start re-processing.",
                  )
                }
                onAskDelete={() => setConfirmId(e.id)}
                onCancelDelete={() => setConfirmId(null)}
                onConfirmDelete={() => void handleDelete(e.id)}
                browserProgress={browserJobs.job?.evidenceId === e.id ? browserJobs.job.progress : null}
                browserBusy={browserJobs.job !== null && browserJobs.job.evidenceId !== e.id}
                browserError={browserJobs.errors[e.id] ?? null}
                onProcessInBrowser={(force) => browserJobs.start(e, force)}
                onCancelBrowser={browserJobs.cancel}
              />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
