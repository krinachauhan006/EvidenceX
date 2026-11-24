"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import clsx from "clsx";
import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { fetchPdfPageImage } from "@/lib/api/analysis";
import type { Segment } from "@/lib/types/processing";
import { bboxPercent } from "@/components/analysis/source-link";
import { percent } from "@/components/analysis/review-labels";
import { segmentTypeLabel } from "@/components/evidence/source-reference";
import { BUTTON, ErrorState } from "@/components/ui/primitives";
import { useObjectUrl } from "@/hooks/use-object-url";
import { claimsBySegment, type ViewerProps } from "@/components/workspace/types";

const PAGE_DPI = 110;
const THUMB_DPI = 24;
const MAX_THUMBS = 60;

function pageOf(s: Segment): number | null {
  if (typeof s.page === "number") return s.page;
  const loc = s.locator as { page?: unknown };
  return typeof loc.page === "number" ? loc.page : null;
}

function Thumb({ caseId, evidenceId, page, active, onClick }: {
  caseId: string;
  evidenceId: string;
  page: number;
  active: boolean;
  onClick: () => void;
}) {
  const { url } = useObjectUrl(
    (signal) => fetchPdfPageImage(caseId, evidenceId, page, THUMB_DPI, signal),
    [caseId, evidenceId, page],
  );
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`Page ${page}`}
      aria-current={active ? "page" : undefined}
      className={clsx(
        "block w-full rounded border p-1 text-center text-[11px]",
        active ? "border-slate-300 bg-navy-800 text-slate-100" : "border-navy-800 text-slate-500 hover:border-navy-600",
      )}
    >
      {url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={url} alt="" className="mx-auto w-full bg-white" />
      ) : (
        <span className="block h-16 bg-navy-950" />
      )}
      {page}
    </button>
  );
}

export function PdfViewer(props: ViewerProps) {
  const { caseId, evidenceId, segments, claims, focusSegmentId, focusPage, onFocusSegment, metadata } = props;
  const pageCount =
    typeof metadata.page_count === "number"
      ? metadata.page_count
      : Math.max(1, ...segments.map((s) => pageOf(s) ?? 1));
  const focusSeg = segments.find((s) => s.id === focusSegmentId) ?? null;
  const [page, setPage] = useState<number>(focusPage ?? (focusSeg ? pageOf(focusSeg) : null) ?? 1);
  const textRef = useRef<HTMLDivElement | null>(null);
  const anchored = useMemo(() => claimsBySegment(claims), [claims]);

  useEffect(() => {
    const p = focusSeg ? pageOf(focusSeg) : null;
    if (p) setPage(p);
  }, [focusSeg]);

  useEffect(() => {
    if (!focusSegmentId || !textRef.current) return;
    textRef.current.querySelector(`[data-seg="${focusSegmentId}"]`)?.scrollIntoView({ block: "nearest" });
  }, [focusSegmentId, page]);

  const image = useObjectUrl(
    (signal) => fetchPdfPageImage(caseId, evidenceId, page, PAGE_DPI, signal),
    [caseId, evidenceId, page],
  );
  const onPage = segments.filter((s) => pageOf(s) === page);

  return (
    <div className="grid gap-4 lg:grid-cols-[6rem_minmax(0,1fr)_minmax(0,22rem)]">
      <div className="hidden max-h-[44rem] space-y-2 overflow-y-auto pr-1 lg:block" aria-label="Page thumbnails">
        {Array.from({ length: Math.min(pageCount, MAX_THUMBS) }, (_, i) => i + 1).map((p) => (
          <Thumb key={p} caseId={caseId} evidenceId={evidenceId} page={p} active={p === page} onClick={() => setPage(p)} />
        ))}
        {pageCount > MAX_THUMBS && <p className="text-[11px] text-slate-500">Use the page controls for pages after {MAX_THUMBS}.</p>}
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between text-xs text-slate-400">
          <button type="button" className={BUTTON} disabled={page <= 1} onClick={() => setPage(page - 1)}>
            <ChevronLeft className="h-3.5 w-3.5" aria-hidden /> Previous
          </button>
          <span>
            Page {page} of {pageCount} · rendered preview of the original PDF
          </span>
          <button type="button" className={BUTTON} disabled={page >= pageCount} onClick={() => setPage(page + 1)}>
            Next <ChevronRight className="h-3.5 w-3.5" aria-hidden />
          </button>
        </div>
        {image.error && <ErrorState message={image.error} />}
        <div className="relative mx-auto max-w-3xl bg-white shadow-lg">
          {image.loading && !image.url && (
            <div className="flex h-96 items-center justify-center bg-navy-950 text-slate-500">
              <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
            </div>
          )}
          {image.url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={image.url} alt={`Page ${page} of the original PDF`} className="block w-full" />
          )}
          {image.url &&
            onPage.map((s) => {
              const loc = s.locator as { bbox?: unknown; page_width?: unknown; page_height?: unknown };
              const box = bboxPercent(loc.bbox, loc.page_width, loc.page_height);
              if (!box) return null;
              const focused = s.id === focusSegmentId;
              const hasClaims = anchored.has(s.id);
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => onFocusSegment(s.id)}
                  aria-label={`Text block ${s.seq + 1}`}
                  title={s.text ?? ""}
                  className={clsx(
                    "absolute rounded-sm",
                    focused
                      ? "bg-sky-400/25 ring-2 ring-sky-500"
                      : hasClaims
                        ? "ring-1 ring-slate-500/60 hover:bg-sky-300/15"
                        : "hover:bg-slate-400/10",
                  )}
                  style={{ left: `${box.left}%`, top: `${box.top}%`, width: `${box.width}%`, height: `${box.height}%` }}
                />
              );
            })}
        </div>
      </div>

      <div ref={textRef} className="max-h-[44rem] overflow-y-auto rounded-lg border border-navy-800 bg-navy-900/70 p-3">
        <p className="text-xs font-medium text-slate-300">Extracted text on page {page}</p>
        <p className="text-[11px] text-slate-500">Mechanically extracted; shown as plain text. Click a block to locate it.</p>
        {onPage.length === 0 && <p className="mt-2 text-xs text-slate-500">No text was extracted from this page.</p>}
        <ul className="mt-2 space-y-1.5">
          {onPage.map((s) => (
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
                    {segmentTypeLabel(s.segment_type)} {s.seq + 1}
                    {anchored.get(s.id)?.length ? ` · ${anchored.get(s.id)!.length} claim(s)` : ""}
                  </span>
                  {s.engine_confidence !== null && <span>OCR {percent(s.engine_confidence)}</span>}
                </span>
                <span className="mt-0.5 block whitespace-pre-wrap break-words text-slate-200">{s.text}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
