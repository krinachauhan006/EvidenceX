"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import type { Segment } from "@/lib/types/processing";
import {
  AudioSegmentBody,
  type SegmentPlayback,
  TranscriptBadges,
} from "@/components/evidence/audio-segment";
import { isAudioTranscript } from "@/components/evidence/audio-transcript";
import { parseCells, parseHeaders } from "@/components/evidence/segment-data";
import { describeLocator, segmentTypeLabel } from "@/components/evidence/source-reference";

// A 35-column row would be a wall of text, so show a few cells and let the reader
// expand the rest.
const COLLAPSED_CELLS = 8;

export function SegmentItem({
  segment,
  playback,
}: {
  segment: Segment;
  /** Only passed for audio transcript segments. */
  playback?: SegmentPlayback;
}) {
  const [expanded, setExpanded] = useState(false);
  const audio = isAudioTranscript(segment);
  const ref = describeLocator(segment.locator);
  const cells = parseCells(segment.data);
  const headers = segment.segment_type === "table_header" ? parseHeaders(segment.data) : null;

  const visibleCells = cells && !expanded ? cells.slice(0, COLLAPSED_CELLS) : cells;
  const hiddenCount = cells ? cells.length - COLLAPSED_CELLS : 0;

  return (
    <li className="rounded-md border border-navy-800 bg-navy-950/50 p-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        <span
          title="Where this content came from in the original file"
          className={
            ref.available
              ? "break-all rounded bg-navy-800 px-2 py-0.5 font-mono text-slate-200"
              : "rounded bg-charcoal-800 px-2 py-0.5 text-slate-500"
          }
        >
          {ref.label}
        </span>
        <span className="text-slate-500">
          {segmentTypeLabel(segment.segment_type)} · #{segment.seq}
        </span>
        {audio && <TranscriptBadges reviewStatus={segment.review_status ?? "unreviewed"} />}
        {segment.language && <span className="text-slate-500">language: {segment.language}</span>}
        {segment.engine_confidence !== null && (
          <span
            className="text-slate-500"
            title="Reported by the extraction engine. It is not a measure of factual accuracy."
          >
            engine-reported confidence {Math.round(segment.engine_confidence * 100)}%
          </span>
        )}
      </div>
      {ref.detail && <p className="mt-1 text-xs text-slate-500">{ref.detail}</p>}

      <div className="mt-2 text-sm text-slate-200">
        {audio ? (
          <AudioSegmentBody segment={segment} playback={playback} />
        ) : headers ? (
          <ul className="flex flex-wrap gap-1.5" aria-label="Column headers">
            {headers.map((h, i) => (
              <li
                // Header names can repeat, so the position is part of the key.
                key={`${i}-${h}`}
                className="rounded bg-navy-800 px-2 py-0.5 text-xs text-slate-200"
              >
                {h === "" ? <span className="text-slate-500">(blank)</span> : h}
              </li>
            ))}
          </ul>
        ) : visibleCells ? (
          <>
            <dl className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
              {visibleCells.map((c, i) => (
                <div key={`${i}-${c.column}`} className="min-w-0">
                  <dt className="truncate text-xs text-slate-500" title={c.column}>
                    {c.coord ? <span className="mr-1 font-mono">{c.coord}</span> : null}
                    {c.column}
                  </dt>
                  <dd className="whitespace-pre-wrap break-words text-slate-100">
                    {c.value === "" ? (
                      <span className="text-slate-600">
                        {c.noCachedValue ? "(no cached value)" : "(empty)"}
                      </span>
                    ) : (
                      c.value
                    )}
                    {c.truncated && <span className="ml-1 text-xs text-slate-500">(truncated)</span>}
                    {c.formula && (
                      <span
                        className="ml-2 font-mono text-xs text-slate-500"
                        title="Formula text from the file. EvidenceX does not calculate formulas."
                      >
                        {c.formula}
                      </span>
                    )}
                  </dd>
                </div>
              ))}
            </dl>
            {hiddenCount > 0 && (
              <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                aria-expanded={expanded}
                className="mt-2 inline-flex items-center gap-1 text-xs text-slate-400 hover:text-slate-200"
              >
                <ChevronDown
                  className={expanded ? "h-3.5 w-3.5 rotate-180" : "h-3.5 w-3.5"}
                  aria-hidden
                />
                {expanded ? "Show fewer cells" : `Show all ${cells?.length ?? 0} cells`}
              </button>
            )}
          </>
        ) : segment.text ? (
          // Plain text node only. Extracted text is untrusted and is never HTML.
          <p className="whitespace-pre-wrap break-words">{segment.text}</p>
        ) : (
          <p className="text-slate-600">(no text)</p>
        )}
      </div>
    </li>
  );
}
