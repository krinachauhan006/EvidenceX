"use client";

import { Loader2, X } from "lucide-react";
import type { Phase, Progress } from "@/lib/browser-processing/run";

const PHASE_TEXT: Record<Phase, string> = {
  checking: "Checking what this browser supports",
  downloading: "Downloading the file from the server",
  claiming: "Reserving the file for this browser",
  "loading-engine": "Loading the engine",
  recognizing: "Reading text (OCR) on this device",
  transcribing: "Transcribing speech on this device. This can take about as long as the recording",
  sampling: "Reading sampled video frames on this device",
  saving: "Sending the results to the server for checking and saving",
};

export function progressText(p: Progress): string {
  let text = PHASE_TEXT[p.phase];
  if (p.detail) text += `: ${p.detail}`;
  if (p.fraction !== null && p.phase !== "sampling") text += ` (${Math.round(p.fraction * 100)}%)`;
  return `${text}…`;
}

/** Live state of an in-browser processing job for one evidence row. */
export function BrowserProcessPanel({ progress, onCancel }: { progress: Progress; onCancel: () => void }) {
  const pct = progress.fraction === null ? null : Math.round(progress.fraction * 100);
  return (
    <div role="status" aria-live="polite" className="mt-2 rounded-md border border-navy-700 bg-navy-900 px-3 py-2">
      <div className="flex items-start justify-between gap-3">
        <p className="flex items-center gap-2 text-xs font-medium text-slate-200">
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
          {progressText(progress)}
        </p>
        <button
          type="button"
          onClick={onCancel}
          className="inline-flex shrink-0 items-center gap-1 rounded border border-navy-700 px-2 py-0.5 text-xs text-slate-300 hover:bg-navy-800"
        >
          <X className="h-3 w-3" aria-hidden /> Cancel
        </button>
      </div>
      {pct !== null && (
        <div className="mt-2 h-1 overflow-hidden rounded bg-navy-800" aria-hidden>
          <div className="h-full bg-slate-400 transition-[width]" style={{ width: `${pct}%` }} />
        </div>
      )}
      <p className="mt-1.5 text-xs text-slate-500">
        The file is processed on this device; only the extracted text and positions are sent back.
        Keep this tab open until it finishes. Nothing is marked completed until the server has
        checked and saved the result.
      </p>
    </div>
  );
}
