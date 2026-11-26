"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import clsx from "clsx";
import { Clapperboard, Film, Loader2, MessageSquareQuote, ScanText } from "lucide-react";
import { fetchEvidenceBlob, fetchVideoFrame } from "@/lib/api/evidence";
import { bboxPercent } from "@/components/analysis/source-link";
import { percent } from "@/components/analysis/review-labels";
import { formatTimestamp } from "@/components/evidence/source-reference";
import { ErrorState } from "@/components/ui/primitives";
import { useObjectUrl } from "@/hooks/use-object-url";
import { claimsBySegment, type ViewerProps } from "@/components/workspace/types";
import type { Segment } from "@/lib/types/processing";

/** Time on the media timeline of any video segment (frame, frame text or speech). */
export function segmentTime(s: Segment): number | null {
  const loc = s.locator as { kind?: string; t?: unknown; start?: unknown };
  if (loc.kind === "video" && typeof loc.t === "number") return loc.t;
  if (loc.kind === "audio" && typeof loc.start === "number") return loc.start;
  return null;
}

/**
 * Video evidence: the original recording, the frames EvidenceX sampled (each decoded
 * on demand at its exact time), text read on those frames with its region, and the
 * soundtrack transcript. Everything shares one media timeline, so clicking any item
 * seeks the player to the cited moment.
 */
export function VideoViewer(props: ViewerProps) {
  const { caseId, evidenceId, segments, claims, focusSegmentId, focusTime, onFocusSegment, metadata } = props;
  const player = useRef<HTMLVideoElement | null>(null);
  const anchored = useMemo(() => claimsBySegment(claims), [claims]);
  const video = useObjectUrl((signal) => fetchEvidenceBlob(caseId, evidenceId, signal), [caseId, evidenceId]);
  const frames = segments.filter((s) => s.segment_type === "video_frame");
  const ocr = segments.filter((s) => s.segment_type === "video_ocr_line");
  const speech = segments.filter((s) => s.segment_type === "transcript_segment");
  const focused = segments.find((s) => s.id === focusSegmentId) ?? null;
  const [frameT, setFrameT] = useState<number | null>(() => {
    const t = focused ? segmentTime(focused) : focusTime ?? null;
    return t ?? (frames[0] ? segmentTime(frames[0]) : null);
  });
  const [now, setNow] = useState(0);

  function seek(t: number | null, segmentId?: string) {
    if (t === null) return;
    if (player.current) {
      player.current.currentTime = t;
      player.current.pause();
    }
    setNow(t);
    const nearest = frames.reduce<Segment | null>((best, f) => {
      const ft = segmentTime(f) ?? 0;
      return ft <= t + 1e-3 && (!best || ft > (segmentTime(best) ?? 0)) ? f : best;
    }, null);
    setFrameT(nearest ? segmentTime(nearest) : t);
    if (segmentId) onFocusSegment(segmentId);
  }

  useEffect(() => {
    const t = focused ? segmentTime(focused) : focusTime ?? null;
    if (t !== null && video.url) seek(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusSegmentId, focusTime, video.url]);

  // Segments usually arrive after the first render; show the first sampled frame as soon
  // as they do (the initial state above could only see an empty list).
  const firstFrameT = frames.length ? segmentTime(frames[0]) : null;
  useEffect(() => {
    if (frameT === null && firstFrameT !== null) setFrameT(firstFrameT);
  }, [frameT, firstFrameT]);

  const duration = typeof metadata.duration_seconds === "number" ? metadata.duration_seconds : null;
  const sampling = (metadata.sampling ?? {}) as Record<string, unknown>;
  const lineOnFrame = ocr.filter((s) => Math.abs((segmentTime(s) ?? -1) - (frameT ?? -2)) < 1e-3);

  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <div>
          <p className="mb-2 flex items-center gap-1.5 text-xs text-slate-400">
            <Film className="h-3.5 w-3.5" aria-hidden /> Original recording (unaltered)
          </p>
          {video.error && <ErrorState message={video.error} />}
          <div className="overflow-hidden rounded-lg border border-navy-800 bg-black">
            {video.loading && !video.url && (
              <div className="flex aspect-video items-center justify-center text-slate-500">
                <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
              </div>
            )}
            {video.url && (
              <video
                ref={player}
                src={video.url}
                controls
                preload="metadata"
                className="block aspect-video w-full"
                onTimeUpdate={(e) => setNow(e.currentTarget.currentTime)}
                aria-label="Original evidence video"
              />
            )}
          </div>
          <Timeline
            duration={duration}
            now={now}
            frames={frames}
            speech={speech}
            ocr={ocr}
            onSeek={(t, id) => seek(t, id)}
            focusId={focusSegmentId}
          />
          <p className="mt-2 text-[11px] text-slate-500">
            {frames.length} frame{frames.length === 1 ? "" : "s"} were sampled
            {typeof sampling.interval_seconds === "number" ? ` (every ${sampling.interval_seconds} s and at scene changes)` : ""}.
            Moments between samples were not examined. No face recognition or authenticity analysis is performed.
          </p>
        </div>

        <div>
          <p className="mb-2 flex items-center gap-1.5 text-xs text-slate-400">
            <ScanText className="h-3.5 w-3.5" aria-hidden />
            Sampled frame {frameT !== null ? `at ${formatTimestamp(frameT)}` : ""} · decoded on demand
          </p>
          {frameT !== null ? (
            <FrameWithText
              caseId={caseId}
              evidenceId={evidenceId}
              t={frameT}
              lines={lineOnFrame}
              focusId={focusSegmentId}
              onFocus={onFocusSegment}
            />
          ) : (
            <p className="rounded-lg border border-dashed border-navy-700 p-6 text-center text-xs text-slate-500">
              No frames were sampled yet. Process the file first.
            </p>
          )}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <SegmentList
          title="Text read on frames"
          icon={<ScanText className="h-3.5 w-3.5" aria-hidden />}
          empty="No text was found on the sampled frames."
          items={ocr}
          anchored={anchored}
          focusId={focusSegmentId}
          onPick={(s) => seek(segmentTime(s), s.id)}
          confidenceLabel="OCR"
        />
        <SegmentList
          title="Soundtrack transcript"
          icon={<MessageSquareQuote className="h-3.5 w-3.5" aria-hidden />}
          empty={metadata.has_audio === false ? "The video has no audio track." : "No speech was transcribed."}
          items={speech}
          anchored={anchored}
          focusId={focusSegmentId}
          onPick={(s) => seek(segmentTime(s), s.id)}
          confidenceLabel="ASR"
        />
      </div>
    </div>
  );
}

function Timeline({
  duration,
  now,
  frames,
  speech,
  ocr,
  onSeek,
  focusId,
}: {
  duration: number | null;
  now: number;
  frames: Segment[];
  speech: Segment[];
  ocr: Segment[];
  onSeek: (t: number, id?: string) => void;
  focusId: string | null;
}) {
  const end = duration ?? Math.max(1, ...[...frames, ...speech].map((s) => segmentTime(s) ?? 0)) + 1;
  const pos = (t: number) => `${Math.min(100, Math.max(0, (t / end) * 100))}%`;
  return (
    <div className="mt-3 rounded-lg border border-navy-800 bg-navy-900/70 p-3" aria-label="Media timeline">
      <div className="flex justify-between text-[10px] text-slate-500">
        <span>00:00:00</span>
        <span>{formatTimestamp(end)}</span>
      </div>
      <div className="relative mt-1 h-14">
        <div className="absolute inset-x-0 top-3 h-px bg-navy-700" />
        <div className="absolute inset-x-0 top-10 h-px bg-navy-700" />
        <span className="absolute -top-0.5 left-0 text-[9px] uppercase tracking-wider text-slate-600">frames</span>
        <span className="absolute left-0 top-6 text-[9px] uppercase tracking-wider text-slate-600">speech</span>
        {frames.map((f) => {
          const t = segmentTime(f) ?? 0;
          const hasText = ocr.some((o) => Math.abs((segmentTime(o) ?? -1) - t) < 1e-3);
          return (
            <button
              key={f.id}
              type="button"
              title={`Frame at ${formatTimestamp(t)}${hasText ? " · text found" : ""}`}
              aria-label={`Sampled frame at ${formatTimestamp(t)}`}
              onClick={() => onSeek(t, f.id)}
              className={clsx(
                "absolute top-1.5 h-3 w-3 -translate-x-1/2 rotate-45 rounded-[2px] border transition-transform hover:scale-125",
                hasText ? "border-sky-300 bg-sky-500/70" : "border-slate-400 bg-navy-700",
                focusId === f.id && "ring-2 ring-sky-400",
              )}
              style={{ left: pos(t) }}
            />
          );
        })}
        {speech.map((s) => {
          const loc = s.locator as { start?: number; end?: number };
          const a = loc.start ?? 0;
          const b = loc.end ?? a;
          return (
            <button
              key={s.id}
              type="button"
              title={`${formatTimestamp(a)} – ${formatTimestamp(b)}: ${s.text ?? ""}`}
              aria-label={`Speech from ${formatTimestamp(a)}`}
              onClick={() => onSeek(a, s.id)}
              className={clsx(
                "absolute top-[34px] h-3 rounded-full border border-cyan-300/60 bg-cyan-400/30 hover:bg-cyan-400/50",
                focusId === s.id && "ring-2 ring-cyan-300",
              )}
              style={{ left: pos(a), width: `max(6px, calc(${pos(b)} - ${pos(a)}))` }}
            />
          );
        })}
        <div className="pointer-events-none absolute top-0 h-14 w-px bg-amber-300/80" style={{ left: pos(now) }} />
      </div>
    </div>
  );
}

function FrameWithText({
  caseId,
  evidenceId,
  t,
  lines,
  focusId,
  onFocus,
}: {
  caseId: string;
  evidenceId: string;
  t: number;
  lines: Segment[];
  focusId: string | null;
  onFocus: (id: string) => void;
}) {
  const frame = useObjectUrl((signal) => fetchVideoFrame(caseId, evidenceId, t, 960, signal), [caseId, evidenceId, t]);
  return (
    <div className="relative overflow-hidden rounded-lg border border-navy-800 bg-black">
      {frame.loading && !frame.url && (
        <div className="flex aspect-video items-center justify-center text-slate-500">
          <Clapperboard className="h-5 w-5 animate-pulse" aria-hidden />
        </div>
      )}
      {frame.error && <ErrorState message={frame.error} />}
      {frame.url && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={frame.url} alt={`Video frame at ${formatTimestamp(t)}`} className="block w-full" />
      )}
      {frame.url &&
        lines.map((s) => {
          const loc = s.locator as { bbox?: unknown; frame_width?: unknown; frame_height?: unknown };
          const box = bboxPercent(loc.bbox, loc.frame_width, loc.frame_height);
          if (!box) return null;
          return (
            <button
              key={s.id}
              type="button"
              onClick={() => onFocus(s.id)}
              title={`${s.text ?? ""} · OCR ${percent(s.engine_confidence)}`}
              aria-label={`Text on frame: ${s.text ?? ""}`}
              className={clsx(
                "absolute rounded-sm border",
                s.id === focusId ? "border-sky-300 bg-sky-400/25 ring-2 ring-sky-400" : "border-sky-300/60 hover:bg-sky-300/15",
              )}
              style={{ left: `${box.left}%`, top: `${box.top}%`, width: `${box.width}%`, height: `${box.height}%` }}
            />
          );
        })}
    </div>
  );
}

function SegmentList({
  title,
  icon,
  empty,
  items,
  anchored,
  focusId,
  onPick,
  confidenceLabel,
}: {
  title: string;
  icon: React.ReactNode;
  empty: string;
  items: Segment[];
  anchored: Map<string, unknown[]>;
  focusId: string | null;
  onPick: (s: Segment) => void;
  confidenceLabel: string;
}) {
  return (
    <div className="max-h-[22rem] overflow-y-auto rounded-lg border border-navy-800 bg-navy-900/70 p-3">
      <p className="flex items-center gap-1.5 text-xs font-medium text-slate-300">
        {icon}
        {title} ({items.length})
      </p>
      <p className="text-[11px] text-slate-500">
        Machine-read; engine confidence is the engine&apos;s own estimate, not accuracy.
      </p>
      {items.length === 0 && <p className="mt-2 text-xs text-slate-500">{empty}</p>}
      <ul className="mt-2 space-y-1.5">
        {items.map((s) => {
          const t = segmentTime(s);
          const n = anchored.get(s.id)?.length ?? 0;
          return (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => onPick(s)}
                className={clsx(
                  "w-full rounded border px-2 py-1.5 text-left text-xs transition-colors",
                  s.id === focusId ? "border-sky-500/60 bg-sky-500/10" : "border-navy-800 hover:border-navy-600",
                )}
              >
                <span className="flex justify-between text-[11px] text-slate-500">
                  <span className="tabular-nums">
                    {t !== null ? formatTimestamp(t) : "?"}
                    {n ? ` · ${n} claim${n === 1 ? "" : "s"}` : ""}
                  </span>
                  <span>
                    {confidenceLabel} {percent(s.engine_confidence)}
                  </span>
                </span>
                <span className="mt-0.5 block whitespace-pre-wrap break-words font-mono text-slate-200">{s.text}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
