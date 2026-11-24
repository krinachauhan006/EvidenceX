"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import clsx from "clsx";
import { Loader2 } from "lucide-react";
import { fetchEvidenceBlob } from "@/lib/api/evidence";
import { bboxPercent } from "@/components/analysis/source-link";
import { percent } from "@/components/analysis/review-labels";
import { ErrorState } from "@/components/ui/primitives";
import { useObjectUrl } from "@/hooks/use-object-url";
import { claimsBySegment, type ViewerProps } from "@/components/workspace/types";

const LOW_CONFIDENCE = 0.6;

export function ImageViewer(props: ViewerProps) {
  const { caseId, evidenceId, segments, claims, focusSegmentId, onFocusSegment } = props;
  const [showBoxes, setShowBoxes] = useState(true);
  const listRef = useRef<HTMLUListElement | null>(null);
  const anchored = useMemo(() => claimsBySegment(claims), [claims]);
  const image = useObjectUrl((signal) => fetchEvidenceBlob(caseId, evidenceId, signal), [caseId, evidenceId]);
  const lines = segments.filter((s) => s.locator.kind === "image");

  useEffect(() => {
    if (!focusSegmentId || !listRef.current) return;
    listRef.current.querySelector(`[data-seg="${focusSegmentId}"]`)?.scrollIntoView({ block: "nearest" });
  }, [focusSegmentId]);

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
      <div>
        <div className="mb-2 flex items-center justify-between text-xs text-slate-400">
          <span>Original image (unaltered). Boxes show where OCR read each line.</span>
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={showBoxes} onChange={(e) => setShowBoxes(e.target.checked)} />
            Show OCR boxes
          </label>
        </div>
        {image.error && <ErrorState message={image.error} />}
        <div className="relative mx-auto w-fit max-w-full">
          {image.loading && !image.url && (
            <div className="flex h-72 w-96 items-center justify-center bg-navy-950 text-slate-500">
              <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
            </div>
          )}
          {image.url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={image.url} alt="Original evidence image" className="block max-h-[44rem] max-w-full" />
          )}
          {image.url &&
            showBoxes &&
            lines.map((s) => {
              if (s.locator.kind !== "image") return null;
              const box = bboxPercent(s.locator.bbox, s.locator.width, s.locator.height);
              if (!box) return null;
              const low = s.engine_confidence !== null && s.engine_confidence < LOW_CONFIDENCE;
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => onFocusSegment(s.id)}
                  title={`${s.text ?? ""} · OCR confidence ${percent(s.engine_confidence)}`}
                  aria-label={`OCR line ${s.seq + 1}`}
                  className={clsx(
                    "absolute rounded-sm border",
                    s.id === focusSegmentId
                      ? "border-sky-400 bg-sky-400/25 ring-2 ring-sky-500"
                      : low
                        ? "border-dashed border-slate-300/80 hover:bg-white/10"
                        : "border-sky-300/50 hover:bg-sky-300/15",
                  )}
                  style={{ left: `${box.left}%`, top: `${box.top}%`, width: `${box.width}%`, height: `${box.height}%` }}
                />
              );
            })}
        </div>
      </div>
      <div className="max-h-[44rem] overflow-y-auto rounded-lg border border-navy-800 bg-navy-900/70 p-3">
        <p className="text-xs font-medium text-slate-300">OCR text ({lines.length} lines)</p>
        <p className="text-[11px] text-slate-500">
          Machine-read text. Confidence is the OCR engine&apos;s own estimate, not accuracy; dashed boxes are
          below {Math.round(LOW_CONFIDENCE * 100)}%.
        </p>
        {lines.length === 0 && <p className="mt-2 text-xs text-slate-500">No text was recognised.</p>}
        <ul ref={listRef} className="mt-2 space-y-1.5">
          {lines.map((s) => (
            <li key={s.id} data-seg={s.id}>
              <button
                type="button"
                onClick={() => onFocusSegment(s.id)}
                className={clsx(
                  "w-full rounded border px-2 py-1.5 text-left text-xs",
                  s.id === focusSegmentId ? "border-sky-500/60 bg-sky-500/10" : "border-navy-800 hover:border-navy-600",
                )}
              >
                <span className="flex justify-between text-[11px] text-slate-500">
                  <span>
                    Line {s.seq + 1}
                    {anchored.get(s.id)?.length ? ` · ${anchored.get(s.id)!.length} claim(s)` : ""}
                  </span>
                  <span className={s.engine_confidence !== null && s.engine_confidence < LOW_CONFIDENCE ? "text-inconsistency" : ""}>
                    OCR {percent(s.engine_confidence)}
                  </span>
                </span>
                <span className="mt-0.5 block whitespace-pre-wrap break-words font-mono text-slate-200">{s.text}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
