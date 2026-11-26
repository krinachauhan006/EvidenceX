import clsx from "clsx";
import { CheckCircle2, Clock, Info, Loader2, XCircle } from "lucide-react";
import type { ProcessingStatus } from "@/lib/types/evidence";
import type { ExtractionOutcome } from "@/lib/types/processing";

interface Props {
  status: ProcessingStatus;
  /** Outcome of the current run, when there is one. */
  outcome: ExtractionOutcome | null;
  /** Accepted by the server but not started yet (UI-only state). */
  queued: boolean;
  /** null = not known yet. false = no extractor exists for this file type. */
  extractorAvailable: boolean | null;
}

type Tone = "neutral" | "muted" | "success" | "failed";

const TONE_CLASS: Record<Tone, string> = {
  neutral: "bg-navy-700 text-unresolved",
  muted: "bg-charcoal-800 text-slate-500",
  success: "bg-processed/15 text-processed",
  failed: "bg-failed/15 text-failed",
};

interface View {
  label: string;
  tone: Tone;
  icon: "spinner" | "clock" | "check" | "x" | "info" | null;
  title: string;
}

function view({ status, outcome, queued, extractorAvailable }: Props): View {
  if (status === "processing") {
    return { label: "Processing", tone: "neutral", icon: "spinner", title: "Extraction is running." };
  }
  if (queued) {
    return { label: "Queued", tone: "neutral", icon: "clock", title: "Waiting for the extraction to start." };
  }
  if (status === "failed") {
    return { label: "Failed", tone: "failed", icon: "x", title: "The last processing attempt failed." };
  }
  if (status === "completed") {
    // needs_ocr and empty are finished runs that produced no usable text. They are
    // shown as notices, never as plain success.
    if (outcome === "needs_ocr") {
      return {
        label: "Requires OCR",
        tone: "neutral",
        icon: "info",
        title: "No text layer was found. OCR is required to read this file.",
      };
    }
    if (outcome === "empty") {
      return {
        label: "No content",
        tone: "neutral",
        icon: "info",
        title: "The file was processed but no content could be extracted.",
      };
    }
    return { label: "Completed", tone: "success", icon: "check", title: "Extraction completed." };
  }
  if (extractorAvailable === false) {
    return {
      label: "Not available yet",
      tone: "muted",
      icon: null,
      title: "No extractor exists for this file type in this release.",
    };
  }
  return { label: "Pending", tone: "neutral", icon: null, title: "Not processed yet." };
}

export function ProcessingStatusBadge(props: Props) {
  const v = view(props);
  const showPartial =
    props.status === "completed" && !props.queued && props.outcome === "partial";

  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        title={v.title}
        className={clsx(
          "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium",
          TONE_CLASS[v.tone],
        )}
      >
        {v.icon === "spinner" && <Loader2 className="h-3 w-3 animate-spin" aria-hidden />}
        {v.icon === "clock" && <Clock className="h-3 w-3" aria-hidden />}
        {v.icon === "check" && <CheckCircle2 className="h-3 w-3" aria-hidden />}
        {v.icon === "x" && <XCircle className="h-3 w-3" aria-hidden />}
        {v.icon === "info" && <Info className="h-3 w-3" aria-hidden />}
        {v.label}
      </span>
      {showPartial && (
        <span
          title="Some content could not be extracted. See the extraction warnings."
          className="rounded-full bg-navy-700 px-2 py-0.5 text-xs text-unresolved"
        >
          Partial
        </span>
      )}
    </span>
  );
}
