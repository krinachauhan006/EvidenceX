"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { Pause, Play, RotateCcw } from "lucide-react";
import { FINAL_STEP, HERO_STEPS, initialStep, msToNext, shown, stepAt } from "./hero-sequence";

/**
 * Hero illustration (fictional data). Six evidence formats light up in turn, claims
 * are extracted and traced to their sources, related claims converge on one
 * suggested event, and a possible inconsistency is shown with benign alternatives,
 * awaiting human review. The sequence plays once and settles in a readable final
 * state. Hover, keyboard focus or a tap on a source highlights its path. A visible
 * control pauses/resumes; with reduced motion the final state is shown immediately.
 * Pure SVG + CSS transitions: no canvas, no layout shift (fixed viewBox).
 */
type SourceId = "pdf" | "photo" | "audio" | "video" | "email" | "sheet";

const ROW0 = 46;
const ROW = 62;
const SOURCES: { id: SourceId; label: string; kind: string; sub: string; color: string; claim: string }[] = [
  { id: "pdf", label: "Delivery receipt", kind: "PDF", sub: "page 1 · text box", color: "#7dd3fc", claim: "arrived 10:30" },
  { id: "photo", label: "Gate photograph", kind: "JPG", sub: "OCR region", color: "#a5b4fc", claim: "plate KX-4471" },
  { id: "audio", label: "Driver call", kind: "M4A", sub: "00:01:12–00:01:19", color: "#5eead4", claim: "“around noon”" },
  { id: "video", label: "Dock camera", kind: "MP4", sub: "frame 00:04:31", color: "#c4b5fd", claim: "truck at dock 3" },
  { id: "email", label: "Dispatch e-mail", kind: "EML", sub: "Date header", color: "#cbd5e1", claim: "dispatched 08:05" },
  { id: "sheet", label: "Shipment ledger", kind: "XLSX", sub: "Sheet1 · C14", color: "#86efac", claim: "12 pallets" },
];
const AMBER = new Set<SourceId>(["pdf", "audio"]); // the two accounts that may not agree

const SRC_X = 10;
const SRC_W = 176;
const CLAIM_X = 252;
const CLAIM_W = 128;
const EVENT = { x: 492, y: ROW0 + ROW * 2.5 };
const rowY = (i: number) => ROW0 + i * ROW;
const EASE = "cubic-bezier(0.22, 1, 0.36, 1)";
// Text halo in the panel colour so connector lines never run through a label.
const HALO = { paintOrder: "stroke", stroke: "#0e1524", strokeWidth: 4, strokeLinejoin: "round" } as const;

function hexPoints(cx: number, cy: number, r: number): string {
  return Array.from({ length: 6 }, (_, i) => {
    const a = (Math.PI / 3) * i + Math.PI / 6;
    return `${(cx + r * Math.cos(a)).toFixed(1)},${(cy + r * Math.sin(a)).toFixed(1)}`;
  }).join(" ");
}

function fade(visible: boolean, delay = 0, extra = "") {
  return {
    opacity: visible ? 1 : 0,
    transform: visible ? "none" : extra || "translateY(6px)",
    transformBox: "fill-box",
    transformOrigin: "center",
    transition: `opacity 520ms ${EASE} ${delay}ms, transform 620ms ${EASE} ${delay}ms`,
  } as const;
}

export function HeroVisual() {
  const [step, setStep] = useState(0);
  const [paused, setPaused] = useState(false);
  const [reduced, setReduced] = useState(false);
  const [hover, setHover] = useState<SourceId | null>(null);
  const [pinned, setPinned] = useState<SourceId | null>(null);
  const elapsed = useRef(0); // playback time already consumed (ms)
  const startedAt = useRef<number | null>(null);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => {
      setReduced(mq.matches);
      if (mq.matches) {
        elapsed.current = HERO_STEPS[FINAL_STEP].at;
        setStep(initialStep(true));
      }
    };
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  // Advance through the steps with one timer at a time; pausing stores the time used.
  useEffect(() => {
    if (reduced || paused) return;
    const wait = msToNext(elapsed.current);
    if (wait === null) return;
    startedAt.current = performance.now();
    const t = window.setTimeout(() => {
      elapsed.current += wait;
      startedAt.current = null;
      setStep(stepAt(elapsed.current));
    }, wait);
    return () => {
      window.clearTimeout(t);
      if (startedAt.current !== null) elapsed.current += performance.now() - startedAt.current;
      startedAt.current = null;
    };
  }, [step, paused, reduced]);

  const replay = useCallback(() => {
    elapsed.current = 0;
    setPaused(false);
    setPinned(null);
    setStep(0);
  }, []);

  const focus = hover ?? pinned;
  const lit = (id: SourceId) => focus === null || focus === id;
  const on = (phase: Parameters<typeof shown>[0]) => shown(phase, step);
  const settled = step === FINAL_STEP;

  return (
    <figure className="relative min-w-0">
      {/* Ambient electric-blue light pooled behind the panel. Static (no animation), and
          kept inside the panel's own column so it never washes over the hero text. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 rounded-[2rem] bg-[radial-gradient(closest-side,rgba(22,139,255,0.22),rgba(25,185,255,0.07)_62%,transparent)] blur-2xl lg:-inset-4"
      />
      {/* Opaque, elevated neon panel: the photo (laptop included) never shows through.
          Neon edge #19B9FF, electric-blue outer glow #168BFF, cyan inner highlight
          #65DFFF, then contact and drop shadows for depth. The drop shadow is offset
          DOWN (not sideways) so it does not reach the text column. */}
      <div
        className={clsx(
          "evx-motion relative isolate overflow-hidden rounded-2xl border border-[#19B9FF]/70 bg-[#0a1428] bg-[linear-gradient(180deg,#0f2040_0%,#0b1730_34%,#08111f_100%)]",
          "shadow-[inset_0_1px_0_0_rgba(101,223,255,0.35),inset_0_0_0_1px_rgba(101,223,255,0.08),inset_0_0_28px_rgba(25,185,255,0.08),0_0_0_1px_rgba(2,8,23,0.85),0_0_14px_rgba(25,185,255,0.45),0_0_42px_-6px_rgba(22,139,255,0.42),0_24px_48px_-18px_rgba(0,0,0,0.85)]",
          paused && "evx-paused",
        )}
        data-opaque-panel="true"
        data-testid="hero-visual"
        data-step={step}
        data-settled={settled}
      >
        {/* Hairline highlight along the top edge, like light catching a glass bezel. */}
        <div aria-hidden className="pointer-events-none absolute inset-x-6 top-0 z-10 h-px bg-gradient-to-r from-transparent via-[#65DFFF] to-transparent opacity-90" />
        <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-16 bg-gradient-to-b from-[#19B9FF]/[0.07] to-transparent" />
        <div className="flex items-center gap-1.5 border-b border-white/5 bg-navy-950/60 px-4 py-2.5">
          <span className="h-2.5 w-2.5 rounded-full bg-slate-600" />
          <span className="h-2.5 w-2.5 rounded-full bg-slate-700" />
          <span className="h-2.5 w-2.5 rounded-full bg-slate-700" />
          <span className="ml-3 truncate text-[11px] text-slate-400">Case · Missing shipment NS-88421 (fictional)</span>
          <span
            className={clsx(
              "ml-auto inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] transition-colors duration-500",
              on("claims") ? "border-processed/30 bg-processed/10 text-processed" : "border-white/10 text-slate-400",
            )}
          >
            <span className={clsx("h-1.5 w-1.5 rounded-full", on("claims") ? "bg-processed" : "bg-slate-500")} />
            {on("claims") ? "6 of 6 processed" : "processing…"}
          </span>
        </div>

        {/* Narrow screens: the same story as stacked HTML, so labels stay legible. */}
        <div className="space-y-3 p-3 sm:hidden" data-testid="hero-compact">
          <ul className="space-y-1.5">
            {SOURCES.map((s, i) => {
              const active = focus === s.id;
              const amber = AMBER.has(s.id) && on("inconsistency");
              return (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => setPinned((p) => (p === s.id ? null : s.id))}
                    aria-pressed={pinned === s.id}
                    data-mobile-source={s.id}
                    className={clsx(
                      "grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 rounded-lg border px-2 py-1.5 text-left transition-[opacity,border-color] duration-300",
                      active ? "border-sky-400/60 bg-sky-500/[0.06]" : "border-white/[0.08] bg-navy-950/40",
                      focus !== null && !active && "opacity-40",
                    )}
                  >
                    <span
                      className="rounded px-1.5 py-0.5 text-[10px] font-bold text-navy-950 transition-opacity duration-500"
                      style={{ background: s.color, opacity: on("illuminate") ? 1 : 0.35, transitionDelay: step === 1 ? `${i * 140}ms` : "0ms" }}
                    >
                      {s.kind}
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-xs font-medium text-slate-100">{s.label}</span>
                      <span className="block truncate text-[10px] text-slate-400">{s.sub}</span>
                    </span>
                    <span
                      className={clsx(
                        "rounded-full border px-2 py-0.5 font-mono text-[10px] transition-all duration-500",
                        amber ? "border-amber-400/70 bg-amber-500/10 text-amber-200" : "border-slate-500/40 text-slate-200",
                      )}
                      style={{ opacity: on("claims") ? 1 : 0, transform: on("claims") ? "none" : "translateX(-6px)", transitionDelay: step === 2 ? `${i * 90}ms` : "0ms" }}
                    >
                      {s.claim}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <div className="flex items-center gap-3 rounded-lg border border-indigo-300/30 bg-indigo-950/40 px-3 py-2 transition-opacity duration-500" style={{ opacity: on("converge") ? 1 : 0 }}>
            <span className={clsx("h-3 w-3 rounded-full bg-indigo-300", on("event") && "evx-pulse-soft")} aria-hidden />
            <span>
              <span className="block text-sm font-semibold text-slate-50">Arrival · 12 Oct</span>
              <span className="block text-[11px] text-slate-300">Suggested event · 6 accounts</span>
            </span>
          </div>
          <div className="rounded-lg border border-amber-400/50 bg-amber-500/[0.08] px-3 py-2 transition-opacity duration-500" style={{ opacity: on("inconsistency") ? 1 : 0 }}>
            <p className="text-xs font-semibold text-amber-300">⚠ Possible inconsistency</p>
            <p className="text-[11px] text-slate-200">receipt 10:30 vs “around noon” · detection confidence is heuristic</p>
          </div>
          <div className="rounded-lg border border-white/10 bg-navy-950/50 px-3 py-2 transition-opacity duration-500" style={{ opacity: on("alternatives") ? 1 : 0 }}>
            <p className="text-xs font-semibold text-slate-200">Alternative explanations</p>
            <p className="text-[11px] leading-relaxed text-slate-300">the caller is estimating · two visits on the same day · device clocks set differently</p>
          </div>
          <p className="inline-flex items-center gap-2 rounded-full border border-slate-400/30 px-3 py-1 text-[11px] font-medium text-slate-200 transition-opacity duration-500" style={{ opacity: on("review") ? 1 : 0 }}>
            <span className="h-2 w-2 rounded-full bg-slate-400" aria-hidden /> Awaiting human review
          </p>
        </div>

        <svg viewBox="0 0 640 420" className="relative hidden h-auto w-full select-none sm:block" role="img" aria-labelledby="hero-visual-title hero-visual-desc">
          <title id="hero-visual-title">Missing shipment (fictional): six evidence files, one suggested event</title>
          <desc id="hero-visual-desc">
            A delivery receipt PDF, a gate photograph, a driver call recording, a dock camera video, a dispatch e-mail
            and a shipment ledger each yield a claim that links to its exact source location. The claims point to one
            suggested event, the arrival on 12 October. The receipt says 10:30 and the driver says around noon; this
            is shown as a possible inconsistency with alternative explanations, awaiting human review.
          </desc>
          <defs>
            <filter id="hero-glow" x="-60%" y="-60%" width="220%" height="220%">
              <feGaussianBlur stdDeviation="4" result="b" />
              <feMerge>
                <feMergeNode in="b" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            {/* Soft neon bloom for the selected path and the event node (static filter). */}
            <filter id="hero-neon" x="-30%" y="-30%" width="160%" height="160%">
              <feGaussianBlur stdDeviation="2.2" result="b" />
              <feFlood floodColor="#19B9FF" floodOpacity="0.75" />
              <feComposite in2="b" operator="in" result="glow" />
              <feMerge>
                <feMergeNode in="glow" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <linearGradient id="hero-card" x1="0" x2="1">
              <stop offset="0" stopColor="#111b2e" />
              <stop offset="1" stopColor="#0d1526" />
            </linearGradient>
          </defs>

          {/* sources → claims → event, one group per source so hover/focus traces the whole path */}
          {SOURCES.map((s, i) => {
            const y = rowY(i);
            const isOn = lit(s.id);
            const active = focus === s.id;
            const amber = AMBER.has(s.id) && on("inconsistency");
            const srcPath = `M${SRC_X + SRC_W} ${y} C ${SRC_X + SRC_W + 34} ${y}, ${CLAIM_X - 34} ${y}, ${CLAIM_X} ${y}`;
            const evPath = `M${CLAIM_X + CLAIM_W} ${y} C ${CLAIM_X + CLAIM_W + 52} ${y}, ${EVENT.x - 70} ${EVENT.y}, ${EVENT.x - 30} ${EVENT.y}`;
            return (
              <g
                key={s.id}
                tabIndex={0}
                role="button"
                aria-pressed={pinned === s.id}
                aria-label={`${s.label} (${s.kind}), ${s.sub}: claim ${s.claim}${AMBER.has(s.id) ? ", part of a possible inconsistency" : ""}`}
                onMouseEnter={() => setHover(s.id)}
                onMouseLeave={() => setHover(null)}
                onFocus={() => setHover(s.id)}
                onBlur={() => setHover(null)}
                onClick={() => setPinned((p) => (p === s.id ? null : s.id))}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setPinned((p) => (p === s.id ? null : s.id));
                  }
                }}
                className="cursor-pointer outline-none [&:focus-visible_.hero-src]:stroke-sky-300"
                style={{ opacity: isOn ? 1 : 0.32, transition: `opacity 260ms ${EASE}` }}
                data-source={s.id}
              >
                {/* source card */}
                <g style={fade(true)}>
                  <rect
                    className="hero-src"
                    x={SRC_X}
                    y={y - 23}
                    width={SRC_W}
                    height="46"
                    rx="10"
                    fill="url(#hero-card)"
                    stroke={active ? s.color : on("illuminate") ? "rgba(148,163,184,0.28)" : "rgba(255,255,255,0.08)"}
                    strokeWidth={active ? 1.6 : 1}
                    style={{ transition: `stroke 400ms ${EASE} ${on("illuminate") && step === 1 ? i * 140 : 0}ms` }}
                  />
                  <rect
                    x={SRC_X + 10}
                    y={y - 11}
                    width="34"
                    height="22"
                    rx="5"
                    fill={s.color}
                    style={{
                      opacity: on("illuminate") ? 0.95 : 0.25,
                      transition: `opacity 500ms ${EASE} ${step === 1 ? i * 140 : 0}ms`,
                    }}
                  />
                  <text x={SRC_X + 27} y={y + 4} textAnchor="middle" className="fill-navy-950 text-[9px] font-bold tracking-wide">
                    {s.kind}
                  </text>
                  <text x={SRC_X + 54} y={y - 3} className="fill-slate-100 text-[11.5px] font-medium">
                    {s.label}
                  </text>
                  <text x={SRC_X + 54} y={y + 12} className="fill-slate-400 text-[9.5px]">
                    {s.sub}
                  </text>
                  {active && <rect x={SRC_X - 3} y={y - 26} width={SRC_W + 6} height="52" rx="12" fill="none" stroke={s.color} strokeOpacity="0.35" />}
                </g>

                {/* source → claim: drawn once, then a slow flow only on the highlighted path */}
                <path
                  d={srcPath}
                  pathLength={1}
                  fill="none"
                  stroke={s.color}
                  strokeOpacity={active ? 0.95 : 0.55}
                  strokeWidth={active ? 2 : 1.3}
                  filter={active ? "url(#hero-neon)" : undefined}
                  strokeDasharray="1"
                  strokeDashoffset={on("trace") ? 0 : 1}
                  style={{ transition: `stroke-dashoffset 760ms ${EASE} ${step === 3 ? i * 90 : 0}ms, stroke-width 200ms` }}
                />
                {active && settled && <path d={srcPath} fill="none" stroke={s.color} strokeWidth="2" className="evx-dash" strokeOpacity="0.9" />}

                {/* claim → event */}
                <path
                  d={evPath}
                  pathLength={1}
                  fill="none"
                  stroke={amber ? "#f59e0b" : active ? "#65DFFF" : "#3b5274"}
                  strokeOpacity={amber || active ? 0.9 : 0.7}
                  strokeWidth={amber || active ? 1.6 : 1.1}
                  filter={active ? "url(#hero-neon)" : undefined}
                  strokeDasharray="1"
                  strokeDashoffset={on("converge") ? 0 : 1}
                  style={{ transition: `stroke-dashoffset 820ms ${EASE} ${step === 4 ? i * 80 : 0}ms, stroke 500ms` }}
                />

                {/* claim chip */}
                <g style={fade(on("claims"), step === 2 ? i * 90 : 0, "translateX(-8px)")}>
                  <rect
                    x={CLAIM_X}
                    y={y - 14}
                    width={CLAIM_W}
                    height="28"
                    rx="14"
                    fill={amber ? "rgba(245,158,11,0.13)" : "#111a2c"}
                    stroke={amber ? "rgba(245,158,11,0.7)" : active ? s.color : "rgba(148,163,184,0.3)"}
                    style={{ transition: "fill 500ms, stroke 500ms" }}
                  />
                  <text
                    x={CLAIM_X + CLAIM_W / 2}
                    y={y + 4}
                    textAnchor="middle"
                    className={clsx("font-mono text-[10.5px]", amber ? "fill-amber-200" : "fill-slate-200")}
                  >
                    {s.claim}
                  </text>
                </g>
              </g>
            );
          })}

          {/* column labels */}
          <g className="fill-slate-400 text-[9px] font-semibold uppercase tracking-[0.18em]">
            <text x={SRC_X + 2} y="14">Evidence</text>
            <text x={CLAIM_X + 4} y="14" style={fade(on("claims"))}>Claims · cited</text>
            <text x={EVENT.x - 44} y="14" style={fade(on("converge"))}>Event</text>
          </g>

          {/* suggested event */}
          <g style={fade(on("converge"), 0, "scale(0.96)")}>
            {on("event") && <circle cx={EVENT.x} cy={EVENT.y} r="40" fill="#168BFF" className="evx-halo" />}
            <g filter={on("event") ? "url(#hero-neon)" : "url(#hero-glow)"}>
              <polygon
                points={hexPoints(EVENT.x, EVENT.y, 28)}
                fill="#0d1f45"
                stroke={on("event") ? "#19B9FF" : "#475569"}
                strokeWidth="1.8"
                style={{ transition: "stroke 600ms" }}
              />
              <circle cx={EVENT.x} cy={EVENT.y} r="6" fill="#65DFFF" className={on("event") ? "evx-pulse" : undefined} />
            </g>
            <text x={EVENT.x} y={EVENT.y + 48} textAnchor="middle" className="fill-slate-100 text-[12px] font-semibold" style={HALO}>
              Arrival · 12 Oct
            </text>
            <text x={EVENT.x} y={EVENT.y + 63} textAnchor="middle" className="fill-slate-300 text-[9.5px]" style={HALO}>
              Suggested event · 6 accounts
            </text>
          </g>

          {/* possible inconsistency */}
          <g style={fade(on("inconsistency"), 0, "translateY(-6px)")} data-testid="hero-inconsistency">
            <path d={`M${EVENT.x + 14} ${EVENT.y - 26} L ${EVENT.x + 40} ${96}`} stroke="rgba(245,158,11,0.55)" strokeDasharray="3 3" />
            <rect x="436" y="30" width="196" height="66" rx="11" fill="rgba(245,158,11,0.09)" stroke="rgba(245,158,11,0.55)" />
            <text x="450" y="52" className="fill-amber-300 text-[11px] font-semibold">
              ⚠ Possible inconsistency
            </text>
            <text x="450" y="69" className="fill-slate-200 text-[10px]">
              receipt 10:30 vs “around noon”
            </text>
            <text x="450" y="84" className="fill-slate-400 text-[9px]">
              detection confidence is heuristic
            </text>
          </g>

          {/* alternative explanations + review status */}
          <g style={fade(on("alternatives"), 0, "translateY(6px)")} data-testid="hero-alternatives">
            <rect x="436" y="300" width="196" height="76" rx="11" fill="#0d1526" stroke="rgba(148,163,184,0.25)" />
            <text x="450" y="320" className="fill-slate-300 text-[10px] font-semibold">
              Alternative explanations
            </text>
            <text x="450" y="337" className="fill-slate-400 text-[9.5px]">
              • the caller is estimating
            </text>
            <text x="450" y="351" className="fill-slate-400 text-[9.5px]">
              • two visits on the same day
            </text>
            <text x="450" y="365" className="fill-slate-400 text-[9.5px]">
              • device clocks set differently
            </text>
          </g>
          <g style={fade(on("review"))} data-testid="hero-review">
            <rect x="436" y="386" width="196" height="24" rx="12" fill="rgba(148,163,184,0.08)" stroke="rgba(148,163,184,0.35)" />
            <circle cx="452" cy="398" r="3.5" fill="#94a3b8" className={settled ? "evx-pulse-soft" : undefined} />
            <text x="462" y="402" className="fill-slate-200 text-[10px] font-medium">
              Awaiting human review
            </text>
          </g>
        </svg>

        {/* progress through the story; static text, not a live region */}
        <div className="flex items-center gap-3 border-t border-white/5 bg-navy-950/50 px-4 py-2.5">
          <ol className="flex gap-1" aria-hidden>
            {HERO_STEPS.map((s, i) => (
              <li
                key={s.phase}
                className={clsx("h-1 w-4 rounded-full transition-colors duration-500", i <= step ? (i >= 6 ? "bg-amber-400/80" : "bg-sky-400") : "bg-navy-700")}
              />
            ))}
          </ol>
          <p className="truncate text-[11px] text-slate-300" data-testid="hero-step-label">
            <span className="tabular-nums text-slate-400">
              {step + 1}/{HERO_STEPS.length}
            </span>{" "}
            {HERO_STEPS[step].label}
          </p>
        </div>
      </div>

      <figcaption className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-400">
        <span>Illustration with fictional data. Hover, focus or tap a file to trace it.</span>
        {!reduced ? (
          <span className="flex items-center gap-2">
            {settled && (
              <button
                type="button"
                onClick={replay}
                className="inline-flex items-center gap-1.5 rounded-full border border-white/10 px-2.5 py-1 text-slate-200 transition-colors hover:border-white/25 hover:bg-white/5"
              >
                <RotateCcw className="h-3.5 w-3.5" aria-hidden /> Replay
              </button>
            )}
            <button
              type="button"
              onClick={() => setPaused((p) => !p)}
              aria-pressed={paused}
              className="inline-flex items-center gap-1.5 rounded-full border border-white/10 px-2.5 py-1 text-slate-200 transition-colors hover:border-white/25 hover:bg-white/5"
            >
              {paused ? <Play className="h-3.5 w-3.5" aria-hidden /> : <Pause className="h-3.5 w-3.5" aria-hidden />}
              {paused ? "Play animation" : "Pause animation"}
            </button>
          </span>
        ) : (
          <span>Animation off (reduced motion).</span>
        )}
      </figcaption>
    </figure>
  );
}
