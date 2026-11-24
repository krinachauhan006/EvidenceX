"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, isAbortError } from "@/lib/api/client";
import { fetchEvidenceBlob } from "@/lib/api/evidence";
import {
  type PlaybackState,
  type PlaybackWindow,
  playbackErrorText,
  playbackWindow,
  shouldStopPlayback,
} from "@/components/evidence/audio-transcript";

class PlaybackFailure extends Error {
  constructor(readonly kind: "missing" | "decode" | "unsupported" | "other") {
    super(kind);
  }
}

export interface SegmentPlayer {
  state: PlaybackState;
  /** The segment currently loading or playing, by sequence number. */
  activeSeq: number | null;
  error: string | null;
  play: (seq: number, start: number, end: number) => void;
  stop: () => void;
}

/**
 * Plays the ORIGINAL uploaded recording from a segment's start to its end.
 *
 * The file is fetched once, on the first Play, through the case-scoped download
 * endpoint and held as an object URL, so seeking works without server range support
 * and no storage path is involved. Stopping is driven by `timeupdate`, which browsers
 * fire about four times a second, so playback can run up to ~0.25 s past the end.
 */
export function useSegmentPlayer(caseId: string, evidenceId: string): SegmentPlayer {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const windowRef = useRef<PlaybackWindow | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const [state, setState] = useState<PlaybackState>("idle");
  const [activeSeq, setActiveSeq] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reset = useCallback(() => {
    windowRef.current = null;
    setActiveSeq(null);
    setState("idle");
  }, []);

  // Release everything when the viewer closes or switches to another file.
  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
      audioRef.current?.pause();
      audioRef.current?.removeAttribute("src");
      audioRef.current = null;
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    };
  }, [caseId, evidenceId]);

  const ensureAudio = useCallback(async (): Promise<HTMLAudioElement> => {
    if (audioRef.current) return audioRef.current;
    if (typeof window === "undefined" || typeof Audio === "undefined") {
      throw new PlaybackFailure("unsupported");
    }
    const controller = new AbortController();
    controllerRef.current = controller;
    let blob: Blob;
    try {
      blob = await fetchEvidenceBlob(caseId, evidenceId, controller.signal);
    } catch (err) {
      if (isAbortError(err)) throw err;
      throw new PlaybackFailure(err instanceof ApiError && err.status === 404 ? "missing" : "other");
    }
    const url = URL.createObjectURL(blob);
    urlRef.current = url;
    const audio = new Audio();
    audio.preload = "auto";
    audio.addEventListener("timeupdate", () => {
      const current = windowRef.current;
      if (current && shouldStopPlayback(audio.currentTime, current)) {
        audio.pause();
        reset();
      }
    });
    audio.addEventListener("ended", reset);
    audio.src = url;
    audioRef.current = audio;
    return audio;
  }, [caseId, evidenceId, reset]);

  const play = useCallback(
    (seq: number, start: number, end: number) => {
      setError(null);
      setActiveSeq(seq);
      setState("loading");
      void (async () => {
        try {
          const audio = await ensureAudio();
          if (audio.readyState < 1) {
            await new Promise<void>((resolve, reject) => {
              audio.addEventListener("loadedmetadata", () => resolve(), { once: true });
              audio.addEventListener("error", () => reject(new PlaybackFailure("decode")), {
                once: true,
              });
            });
          }
          const range = playbackWindow(start, end, audio.duration);
          if (!range) throw new PlaybackFailure("other");
          windowRef.current = range;
          audio.currentTime = range.start;
          await audio.play();
          setState("playing");
        } catch (err) {
          if (isAbortError(err)) return;
          const kind =
            err instanceof PlaybackFailure
              ? err.kind
              : err instanceof DOMException && err.name === "NotSupportedError"
                ? "decode"
                : "other";
          windowRef.current = null;
          setActiveSeq(null);
          setState(kind === "unsupported" ? "unsupported" : "error");
          setError(playbackErrorText(kind));
        }
      })();
    },
    [ensureAudio],
  );

  const stop = useCallback(() => {
    audioRef.current?.pause();
    reset();
  }, [reset]);

  return { state, activeSeq, error, play, stop };
}
