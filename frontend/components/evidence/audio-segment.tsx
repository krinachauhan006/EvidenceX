"use client";

import { Loader2, Play, Square } from "lucide-react";
import type { Segment } from "@/lib/types/processing";
import { formatProbability, parseTranscriptWords } from "@/components/evidence/audio-transcript";
import { formatTimestamp } from "@/components/evidence/source-reference";

export interface SegmentPlayback {
  /** This segment is the one currently loading or playing. */
  active: boolean;
  loading: boolean;
  onPlay: () => void;
  onStop: () => void;
}

/** Labels that apply to every machine transcript. Used per segment and in the viewer. */
export function TranscriptBadges({ reviewStatus }: { reviewStatus: string }) {
  return (
    <>
      <span
        className="rounded bg-navy-700 px-2 py-0.5 text-slate-200"
        title="Produced automatically by a speech-recognition model. It may contain errors."
      >
        AI-generated transcription
      </span>
      <span
        className="rounded border border-slate-600 px-2 py-0.5 text-slate-300"
        title="No person has checked this text against the recording."
      >
        {reviewStatus === "unreviewed" ? "Unreviewed" : reviewStatus}
      </span>
    </>
  );
}

export function AudioSegmentBody({
  segment,
  playback,
}: {
  segment: Segment;
  playback?: SegmentPlayback;
}) {
  const words = parseTranscriptWords(segment.data);
  const flagged = words?.filter((w) => w.flagged) ?? [];

  return (
    <div className="space-y-2">
      {playback && (
        <button
          type="button"
          onClick={playback.active && !playback.loading ? playback.onStop : playback.onPlay}
          disabled={playback.active && playback.loading}
          aria-label={
            playback.active && !playback.loading
              ? "Stop playback"
              : `Play the original recording from ${formatTimestamp(segment.t_start ?? 0)}`
          }
          className="inline-flex items-center gap-1.5 rounded-md border border-navy-700 px-2.5 py-1 text-xs text-slate-200 hover:bg-navy-800 disabled:opacity-50"
        >
          {playback.active && playback.loading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : playback.active ? (
            <Square className="h-3.5 w-3.5" aria-hidden />
          ) : (
            <Play className="h-3.5 w-3.5" aria-hidden />
          )}
          {playback.active && !playback.loading ? "Stop" : "Play this segment"}
        </button>
      )}

      <div>
        <p className="text-xs text-slate-500">Original transcript (exactly as recognised)</p>
        {/* Plain text node only. The stored text is never rewritten or corrected. */}
        <p className="whitespace-pre-wrap break-words text-slate-100">
          {segment.text ?? <span className="text-slate-600">(no text)</span>}
        </p>
      </div>

      {words ? (
        <div>
          <p className="text-xs text-slate-500">
            Word detail{flagged.length > 0 ? " · dashed underline = possibly misheard" : ""}
          </p>
          <p className="mt-0.5 flex flex-wrap gap-x-1 gap-y-0.5" aria-label="Recognised words">
            {words.map((w, i) => (
              <span
                // Words repeat, so the position is part of the key.
                key={`${i}-${w.word}`}
                title={`${formatTimestamp(w.start)} – ${formatTimestamp(w.end)} · engine-reported probability ${formatProbability(w.probability)}`}
                data-flagged={w.flagged ? "true" : undefined}
                className={
                  w.flagged
                    ? "rounded bg-navy-700 px-0.5 text-slate-100 underline decoration-slate-300 decoration-dashed underline-offset-4"
                    : "text-slate-400"
                }
              >
                {w.word}
              </span>
            ))}
          </p>
          {flagged.length > 0 && (
            <ul className="mt-1.5 space-y-0.5 text-xs text-slate-400" aria-label="Possibly misheard words">
              {flagged.map((w, i) => (
                <li key={`${i}-${w.word}`}>
                  <span className="font-medium text-slate-200">{w.word}</span> at{" "}
                  <span className="font-mono">{formatTimestamp(w.start)}</span> · engine-reported
                  probability {formatProbability(w.probability)} — check against the recording
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <p className="text-xs text-slate-500">
          Word-level detail is not available for this run. Runs processed before word
          timestamps were enabled do not have it; process the file again to add it.
        </p>
      )}
    </div>
  );
}
