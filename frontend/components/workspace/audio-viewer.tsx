"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import clsx from "clsx";
import { Loader2, Pencil, Play, Square } from "lucide-react";
import { addSegmentReview } from "@/lib/api/analysis";
import { fetchEvidenceBlob } from "@/lib/api/evidence";
import { formatDateTime } from "@/lib/format";
import type { Segment } from "@/lib/types/processing";
import {
  VERIFY_NOTICE,
  formatProbability,
  parseTranscriptWords,
  playbackWindow,
  shouldStopPlayback,
  transcriptSpans,
  type PlaybackWindow,
} from "@/components/evidence/audio-transcript";
import { formatTimestamp } from "@/components/evidence/source-reference";
import { percent } from "@/components/analysis/review-labels";
import { Badge, BUTTON, ErrorState, INPUT } from "@/components/ui/primitives";
import { errorText } from "@/hooks/use-api";
import { useObjectUrl } from "@/hooks/use-object-url";
import { useReviewer } from "@/hooks/use-reviewer";
import { claimsBySegment, type ViewerProps } from "@/components/workspace/types";

export function AudioViewer(props: ViewerProps) {
  const { caseId, evidenceId, segments, claims, focusSegmentId, focusTime, onFocusSegment, onSegmentsChanged } = props;
  const audio = useObjectUrl((signal) => fetchEvidenceBlob(caseId, evidenceId, signal), [caseId, evidenceId]);
  const playerRef = useRef<HTMLAudioElement | null>(null);
  const windowRef = useRef<PlaybackWindow | null>(null);
  const listRef = useRef<HTMLUListElement | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const [current, setCurrent] = useState(0);
  const anchored = useMemo(() => claimsBySegment(claims), [claims]);
  const transcript = segments.filter((s) => s.locator.kind === "audio");

  function playSegment(s: Segment, from?: number | null) {
    const el = playerRef.current;
    if (!el || s.locator.kind !== "audio") return;
    const start = from ?? s.locator.start;
    const range = playbackWindow(start, s.locator.end, Number.isFinite(el.duration) ? el.duration : null);
    if (!range) return;
    windowRef.current = range;
    el.currentTime = range.start;
    void el.play().then(() => setPlaying(s.id)).catch(() => setPlaying(null));
  }

  function stop() {
    playerRef.current?.pause();
    windowRef.current = null;
    setPlaying(null);
  }

  // Jump to the focused segment (from a claim): scroll and cue at the word time.
  useEffect(() => {
    if (!focusSegmentId) return;
    listRef.current?.querySelector(`[data-seg="${focusSegmentId}"]`)?.scrollIntoView({ block: "center" });
    const s = transcript.find((x) => x.id === focusSegmentId);
    const el = playerRef.current;
    if (s && el && s.locator.kind === "audio") {
      const cue = () => {
        el.currentTime = focusTime ?? (s.locator.kind === "audio" ? s.locator.start : 0);
      };
      if (el.readyState >= 1) cue();
      else el.addEventListener("loadedmetadata", cue, { once: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusSegmentId, focusTime, audio.url]);

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-navy-800 bg-navy-900/70 p-3">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Badge>AI-generated transcription</Badge>
          <Badge>Machine output, unreviewed unless marked</Badge>
        </div>
        <p className="mt-1.5 text-xs text-slate-300">{VERIFY_NOTICE}</p>
        {audio.error && <ErrorState message={audio.error} />}
        {audio.loading && !audio.url && (
          <p className="mt-2 flex items-center gap-2 text-xs text-slate-500">
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> Loading the original recording…
          </p>
        )}
        {audio.url && (
          <audio
            ref={playerRef}
            src={audio.url}
            controls
            preload="metadata"
            className="mt-2 w-full"
            onTimeUpdate={(e) => {
              const t = e.currentTarget.currentTime;
              setCurrent(t);
              const w = windowRef.current;
              if (w && shouldStopPlayback(t, w)) stop();
            }}
            onPause={() => setPlaying(null)}
          >
            Your browser cannot play this recording.
          </audio>
        )}
      </div>

      <ul ref={listRef} className="space-y-2" aria-label="Transcript segments">
        {transcript.map((s) => (
          <TranscriptRow
            key={s.id}
            caseId={caseId}
            evidenceId={evidenceId}
            segment={s}
            focused={s.id === focusSegmentId}
            playing={playing === s.id}
            nowPlaying={s.locator.kind === "audio" && current >= s.locator.start && current < s.locator.end}
            claimCount={anchored.get(s.id)?.length ?? 0}
            canPlay={Boolean(audio.url)}
            onPlay={() => playSegment(s)}
            onStop={stop}
            onFocus={() => onFocusSegment(s.id)}
            onSaved={onSegmentsChanged}
          />
        ))}
      </ul>
      {transcript.length === 0 && <p className="text-sm text-slate-500">No speech segments were transcribed.</p>}
    </div>
  );
}

function TranscriptRow({
  caseId,
  evidenceId,
  segment: s,
  focused,
  playing,
  nowPlaying,
  claimCount,
  canPlay,
  onPlay,
  onStop,
  onFocus,
  onSaved,
}: {
  caseId: string;
  evidenceId: string;
  segment: Segment;
  focused: boolean;
  playing: boolean;
  nowPlaying: boolean;
  claimCount: number;
  canPlay: boolean;
  onPlay: () => void;
  onStop: () => void;
  onFocus: () => void;
  onSaved?: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(s.reviewed_text ?? s.text ?? "");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewer] = useReviewer();
  const words = parseTranscriptWords(s.data);
  const start = s.locator.kind === "audio" ? s.locator.start : 0;
  const end = s.locator.kind === "audio" ? s.locator.end : 0;

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await addSegmentReview(caseId, evidenceId, s.id, {
        corrected_text: text.trim(),
        note: note.trim() || undefined,
        reviewer: reviewer || undefined,
      });
      setEditing(false);
      onSaved?.();
    } catch (err) {
      setError(errorText(err, "The correction could not be saved."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li
      data-seg={s.id}
      className={clsx(
        "rounded-lg border p-3 text-sm",
        focused ? "border-sky-500/60 bg-sky-500/5" : nowPlaying ? "border-navy-600 bg-navy-800/40" : "border-navy-800 bg-navy-900/70",
      )}
    >
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <button type="button" className={BUTTON} disabled={!canPlay} onClick={playing ? onStop : onPlay}>
          {playing ? <Square className="h-3 w-3" aria-hidden /> : <Play className="h-3 w-3" aria-hidden />}
          {formatTimestamp(start)} – {formatTimestamp(end)}
        </button>
        <span>Engine confidence {percent(s.engine_confidence)}</span>
        {s.review_status === "reviewed" ? (
          <Badge tone="green">Corrected by {s.reviewed_by ?? "a reviewer"}</Badge>
        ) : (
          <Badge>Unreviewed</Badge>
        )}
        {claimCount > 0 && (
          <button type="button" onClick={onFocus} className="text-sky-300 hover:underline">
            {claimCount} claim{claimCount === 1 ? "" : "s"}
          </button>
        )}
      </div>

      <p className="mt-2 text-[11px] uppercase tracking-wider text-slate-500">Machine transcript (exactly as stored)</p>
      {/* The stored text is the authority. Spans only add highlighting; joined, they are
          identical to s.text. Tokens are never re-joined to build the text. */}
      <p className="mt-0.5 whitespace-pre-wrap break-words text-slate-200" data-testid="verbatim-transcript">
        {transcriptSpans(s.text, words).map((span, i) =>
          span.word ? (
            <span
              key={i}
              title={`${formatTimestamp(span.word.start)} · engine probability ${formatProbability(span.word.probability)}`}
              data-flagged={span.word.flagged ? "true" : undefined}
              className={
                span.word.flagged
                  ? "rounded bg-navy-700 text-slate-100 underline decoration-inconsistency decoration-dashed underline-offset-4"
                  : undefined
              }
            >
              {span.text}
            </span>
          ) : (
            <span key={i}>{span.text}</span>
          ),
        )}
        {!s.text && <span className="text-slate-600">(no text)</span>}
      </p>
      {words?.some((w) => w.flagged) && (
        <p className="mt-1 text-[11px] text-slate-500">Dashed underline: the engine rated the word as possibly misheard.</p>
      )}
      {words && words.length > 0 && (
        <details className="mt-1.5 text-xs text-slate-400">
          <summary className="cursor-pointer text-slate-500 hover:text-slate-300">
            Word tokens ({words.length}): engine detail, not the transcript text
          </summary>
          <ol className="mt-1 flex flex-wrap gap-1" aria-label="Recognised word tokens">
            {words.map((w, i) => (
              <li
                key={`${i}-${w.word}`}
                data-flagged={w.flagged ? "true" : undefined}
                className={
                  w.flagged
                    ? "rounded border border-dashed border-inconsistency/60 bg-navy-800 px-1.5 py-0.5 font-mono text-slate-100"
                    : "rounded border border-navy-700 bg-navy-900 px-1.5 py-0.5 font-mono"
                }
              >
                {w.word}
                <span className="ml-1 text-[10px] text-slate-500">
                  {formatTimestamp(w.start)} · {formatProbability(w.probability)}
                </span>
              </li>
            ))}
          </ol>
        </details>
      )}

      {s.review_status === "reviewed" && s.reviewed_text && (
        <div className="mt-2 rounded-md border border-processed/30 bg-processed/5 px-3 py-2">
          <p className="text-[11px] uppercase tracking-wider text-processed">
            Human correction · {s.reviewed_by ?? "unspecified"} · {formatDateTime(s.reviewed_at)}
          </p>
          <p className="mt-0.5 whitespace-pre-wrap break-words text-slate-100">{s.reviewed_text}</p>
        </div>
      )}

      <div className="mt-2">
        <button type="button" className={BUTTON} onClick={() => setEditing((v) => !v)}>
          <Pencil className="h-3 w-3" aria-hidden /> {editing ? "Cancel" : "Correct transcript"}
        </button>
      </div>
      {editing && (
        <div className="mt-2 space-y-2 rounded-md border border-navy-800 bg-navy-950/60 p-3">
          <p className="text-[11px] text-slate-500">
            Listen to the segment first. The machine text, timestamps and probabilities are kept; your
            correction is stored separately with your name and the time.
          </p>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} maxLength={20000} className={INPUT} aria-label="Corrected transcript" />
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)" maxLength={4000} className={INPUT} />
          <button type="button" className={BUTTON} disabled={busy || !text.trim()} onClick={() => void save()}>
            {busy && <Loader2 className="h-3 w-3 animate-spin" aria-hidden />} Save correction
          </button>
          {error && <p role="alert" className="text-xs text-failed">{error}</p>}
        </div>
      )}
    </li>
  );
}
