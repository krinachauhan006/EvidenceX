"use client";

// Interactive explainers for the public landing page. Every example uses clearly
// labelled fictional data and shows how EvidenceX actually behaves; nothing here
// is a statistic or a customer result.

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import clsx from "clsx";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  ChevronDown,
  Cpu,
  FileSearch,
  FileText,
  Menu,
  Network,
  ScanLine,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";
import { me } from "@/lib/api/auth";
import { Brand } from "@/components/layout/brand";

// --- navigation -------------------------------------------------------------------

const LINKS = [
  { href: "#how-it-works", label: "How it works" },
  { href: "#provenance", label: "Provenance" },
  { href: "#events", label: "Events" },
  { href: "#graph", label: "Graph" },
  { href: "#trust", label: "Limits" },
];

/** True once the API confirms a session. Never blocks rendering of the page. */
function useSignedIn(): boolean {
  const [signedIn, setSignedIn] = useState(false);
  useEffect(() => {
    const c = new AbortController();
    me(c.signal)
      .then(() => setSignedIn(true))
      .catch(() => setSignedIn(false));
    return () => c.abort();
  }, []);
  return signedIn;
}

/** Which section is under the header: the last one whose top has passed 40% of the viewport. */
function useActiveSection(ids: string[]): string | null {
  const [active, setActive] = useState<string | null>(null);
  useEffect(() => {
    let frame = 0;
    const measure = () => {
      frame = 0;
      let current: string | null = null;
      for (const id of ids) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top <= window.innerHeight * 0.4) current = id;
      }
      setActive(current);
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(measure);
    };
    measure();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [ids]);
  return active;
}

const SECTION_IDS = LINKS.map((l) => l.href.slice(1));

export function LandingNav() {
  const signedIn = useSignedIn();
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const active = useActiveSection(SECTION_IDS);
  const menuRef = useRef<HTMLDivElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Mobile menu: Escape closes and returns focus; widening to desktop closes it.
  useEffect(() => {
    if (!open) return;
    menuRef.current?.querySelector<HTMLElement>("a")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        toggleRef.current?.focus();
      }
    };
    const mq = window.matchMedia("(min-width: 1024px)");
    const onWide = () => mq.matches && setOpen(false);
    window.addEventListener("keydown", onKey);
    mq.addEventListener("change", onWide);
    return () => {
      window.removeEventListener("keydown", onKey);
      mq.removeEventListener("change", onWide);
    };
  }, [open]);

  return (
    <header
      className={clsx(
        "sticky top-0 z-50 border-b transition-[background-color,border-color,box-shadow] duration-300",
        scrolled || open
          ? "border-white/10 bg-navy-950/85 shadow-[0_8px_30px_-12px_rgba(0,0,0,0.8)] backdrop-blur-md"
          : "border-transparent bg-navy-950/40 backdrop-blur-sm",
      )}
      data-testid="landing-header"
      data-scrolled={scrolled}
    >
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 md:px-8">
        <Brand />
        <nav className="hidden items-center gap-1 text-sm lg:flex" aria-label="Page sections">
          {LINKS.map((l) => {
            const on = active === l.href.slice(1);
            return (
              <a
                key={l.href}
                href={l.href}
                aria-current={on ? "location" : undefined}
                className={clsx(
                  "rounded-md px-3 py-1.5 transition-colors",
                  on ? "bg-white/[0.06] text-slate-50" : "text-slate-300 hover:bg-white/[0.04] hover:text-slate-50",
                )}
              >
                {l.label}
              </a>
            );
          })}
        </nav>
        <div className="hidden items-center gap-2 lg:flex">
          {signedIn ? (
            <Link href="/cases" className="rounded-md bg-sky-500 px-3.5 py-1.5 text-sm font-semibold text-navy-950 hover:bg-sky-400">
              Open workspace
            </Link>
          ) : (
            <>
              <Link href="/login" className="rounded-md px-3 py-1.5 text-sm text-slate-300 hover:text-slate-50">
                Sign in
              </Link>
              <Link href="/register" className="rounded-md bg-sky-500 px-3.5 py-1.5 text-sm font-semibold text-navy-950 hover:bg-sky-400">
                Start an Investigation
              </Link>
            </>
          )}
        </div>
        <button
          ref={toggleRef}
          type="button"
          className="rounded-md border border-navy-700 p-2 text-slate-200 transition-colors hover:bg-white/5 lg:hidden"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls="landing-mobile-menu"
          aria-label={open ? "Close menu" : "Open menu"}
          data-testid="mobile-menu-toggle"
        >
          {open ? <X className="h-5 w-5" aria-hidden /> : <Menu className="h-5 w-5" aria-hidden />}
        </button>
      </div>
      {open && (
        <div id="landing-mobile-menu" ref={menuRef} className="evx-page border-t border-white/10 px-4 pb-4 lg:hidden">
          <nav className="flex flex-col py-2 text-sm text-slate-200" aria-label="Page sections (menu)">
            {LINKS.map((l) => (
              <a
                key={l.href}
                href={l.href}
                onClick={() => setOpen(false)}
                aria-current={active === l.href.slice(1) ? "location" : undefined}
                className="rounded-md px-2 py-2.5 hover:bg-white/5 aria-[current=location]:text-sky-200"
              >
                {l.label}
              </a>
            ))}
          </nav>
          <Link href={signedIn ? "/cases" : "/register"} className="block rounded-md bg-sky-500 px-3.5 py-2 text-center text-sm font-semibold text-navy-950">
            {signedIn ? "Open workspace" : "Start an Investigation"}
          </Link>
          {!signedIn && (
            <Link href="/login" className="mt-2 block text-center text-sm text-slate-400">
              Sign in
            </Link>
          )}
        </div>
      )}
    </header>
  );
}

export function PrimaryCta({ className }: { className?: string }) {
  const signedIn = useSignedIn();
  return (
    <Link
      href={signedIn ? "/cases" : "/register"}
      className={clsx(
        "group inline-flex items-center gap-2 rounded-lg bg-sky-500 px-5 py-3 text-sm font-semibold text-navy-950 shadow-[0_0_40px_-8px_rgba(56,189,248,0.7)] transition hover:bg-sky-400",
        className,
      )}
    >
      {signedIn ? "Open your workspace" : "Start an Investigation"}
      <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
    </Link>
  );
}

// --- C. how it works ------------------------------------------------------------------

const STEPS = [
  {
    icon: Upload,
    title: "Upload",
    short: "Every file is checked by its content",
    body: "PDF, images, audio, video, e-mail, CSV and XLSX. The real file type is read from its bytes, not its name; sizes are capped; files are stored under their SHA-256 and never executed.",
    detail: ["magic-byte validation", "per-type size limits", "content-addressed storage"],
  },
  {
    icon: ScanLine,
    title: "Extract",
    short: "Text keeps its exact location",
    body: "Embedded PDF text, OCR for scans and photos (with orientation and deskew, boxes mapped back to the original), speech recognition for audio and video soundtracks, sampled video frames, table cells and e-mail parts.",
    detail: ["page + box", "timestamp", "row / cell", "frame time + region"],
  },
  {
    icon: Cpu,
    title: "Connect",
    short: "Claims, entities and proposed events",
    body: "Statements with a time, date, quantity, identifier or place become claims that quote their source. Identical identifiers link records; similar ones are offered as tiered candidates. Claims that may describe one occurrence are proposed as events.",
    detail: ["rule-based by default", "AI only with case consent", "nothing merged automatically"],
  },
  {
    icon: AlertTriangle,
    title: "Compare",
    short: "Possible inconsistencies, with alternatives",
    body: "Accounts are compared once a reviewer confirms they describe one event. Each possible inconsistency states both sources, why they may differ, what is uncertain, benign alternatives, and a heuristic detection confidence.",
    detail: ["tolerance & rounding", "time-zone hints", "missing ≠ conflicting"],
  },
  {
    icon: FileText,
    title: "Review & report",
    short: "People decide; every decision is recorded",
    body: "Reviewers confirm, reject, merge or defer. Each action is signed by the account that made it and chained by hash. Reports are versioned PDFs with the hash of their content.",
    detail: ["roles: owner → viewer", "tamper-evident audit", "PDF, JSON, GraphML"],
  },
];

export function PipelineStepper() {
  const [active, setActive] = useState(0);
  const step = STEPS[active];
  const Icon = step.icon;
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <ol className="relative space-y-2" aria-label="Pipeline steps">
        <span aria-hidden className="absolute bottom-6 left-[1.35rem] top-6 w-px bg-gradient-to-b from-sky-500/60 via-indigo-500/40 to-transparent" />
        {STEPS.map((s, i) => {
          const I = s.icon;
          const on = i === active;
          return (
            <li key={s.title}>
              <button
                type="button"
                onClick={() => setActive(i)}
                onMouseEnter={() => setActive(i)}
                aria-current={on ? "step" : undefined}
                className={clsx(
                  "relative flex w-full items-center gap-4 rounded-xl border px-3 py-3 text-left transition-colors",
                  on ? "border-sky-500/40 bg-sky-500/[0.07]" : "border-transparent hover:bg-white/[0.03]",
                )}
              >
                <span
                  className={clsx(
                    "relative z-10 flex h-11 w-11 shrink-0 items-center justify-center rounded-full border transition-colors",
                    on ? "border-sky-400 bg-sky-500/20 text-sky-200" : "border-navy-700 bg-navy-900 text-slate-400",
                  )}
                >
                  <I className="h-5 w-5" aria-hidden />
                </span>
                <span>
                  <span className="block text-xs font-medium uppercase tracking-wider text-slate-500">Step {i + 1}</span>
                  <span className="block font-medium text-slate-100">{s.title}</span>
                  <span className="block text-sm text-slate-400">{s.short}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      <div key={active} className="evx-page relative overflow-hidden rounded-2xl border border-white/10 bg-navy-900/70 p-6">
        <div aria-hidden className="evx-grid-bg pointer-events-none absolute inset-0" />
        <div className="relative">
          <span className="flex h-12 w-12 items-center justify-center rounded-xl border border-sky-500/40 bg-sky-500/10 text-sky-200">
            <Icon className="h-6 w-6" aria-hidden />
          </span>
          <h3 className="mt-4 text-xl font-semibold text-slate-50">
            {active + 1}. {step.title}
          </h3>
          <p className="mt-2 text-sm leading-relaxed text-slate-300">{step.body}</p>
          <ul className="mt-4 flex flex-wrap gap-2">
            {step.detail.map((d) => (
              <li key={d} className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-xs text-slate-300">
                {d}
              </li>
            ))}
          </ul>
          <div className="mt-6 flex gap-1" aria-hidden>
            {STEPS.map((_, i) => (
              <span key={i} className={clsx("h-1 flex-1 rounded-full transition-colors", i <= active ? "bg-sky-400" : "bg-navy-700")} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// --- E. provenance demo ---------------------------------------------------------------

const DOC_LINES = [
  "DELIVERY RECEIPT  ·  No. DR-20931",
  "Consignee: Warehouse A, Bay 3",
  "Shipment NS-88421 received in full.",
  "Truck KX-4471 arrived 10:30 on 12 October 2026.",
  "Pallets counted: 12",
  "Signed: R. Mehta (receiving clerk)",
];

const DEMO_CLAIMS = [
  { line: 3, type: "time", text: "Truck KX-4471 arrived 10:30", conf: "page 1 · box (72, 214)–(468, 230) pt" },
  { line: 2, type: "identifier", text: "Shipment NS-88421 received", conf: "page 1 · box (72, 190)–(332, 206) pt" },
  { line: 4, type: "quantity", text: "12 pallets counted", conf: "page 1 · box (72, 238)–(238, 254) pt" },
];

export function ProvenanceDemo() {
  const [active, setActive] = useState(0);
  const claim = DEMO_CLAIMS[active];
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
      <div className="rounded-2xl border border-white/10 bg-navy-900/70 p-4">
        <p className="mb-3 text-xs font-medium uppercase tracking-wider text-slate-500">Extracted claims · fictional</p>
        <ul className="space-y-2">
          {DEMO_CLAIMS.map((c, i) => (
            <li key={c.text}>
              <button
                type="button"
                onClick={() => setActive(i)}
                onMouseEnter={() => setActive(i)}
                aria-pressed={i === active}
                className={clsx(
                  "w-full rounded-xl border p-3 text-left transition-all",
                  i === active ? "border-sky-500/50 bg-sky-500/10 shadow-[0_0_30px_-12px_rgba(56,189,248,0.8)]" : "border-navy-800 hover:border-navy-600",
                )}
              >
                <span className="flex items-center gap-2 text-[11px] text-slate-500">
                  <span className="rounded-full border border-navy-600 px-2 py-0.5 capitalize">{c.type}</span>
                  unreviewed
                </span>
                <span className="mt-1 block font-mono text-sm text-slate-100">“{c.text}”</span>
                <span className="mt-1 block text-[11px] text-slate-500">receipt.pdf · {c.conf}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="relative rounded-2xl border border-white/10 bg-[#f6f4ee] p-6 text-[#1b2433] shadow-2xl shadow-black/40" aria-label="Source document">
        <p className="mb-1 text-[10px] uppercase tracking-widest text-gray-600">receipt.pdf · page 1 (original, unaltered)</p>
        <div className="space-y-2 font-mono text-[13px]">
          {DOC_LINES.map((l, i) => (
            <p
              key={l}
              className={clsx(
                "rounded px-1.5 py-0.5 transition-all duration-300",
                i === claim.line ? "bg-sky-400/30 ring-2 ring-sky-500" : "",
                i === 0 && "font-bold",
              )}
            >
              {l}
            </p>
          ))}
        </div>
        <p className="mt-4 flex items-center gap-1.5 text-[11px] text-gray-700">
          <FileSearch className="h-3.5 w-3.5" aria-hidden /> Clicking a claim in EvidenceX opens this page at this box.
        </p>
      </div>
    </div>
  );
}

// --- F. events and comparisons --------------------------------------------------------

const ACCOUNTS = [
  { label: "Delivery receipt", at: 630, colour: "#38bdf8", quote: "Truck arrived 10:30" },
  { label: "Gate log", at: 632, colour: "#34d399", quote: "Truck in 10:32" },
  { label: "Witness audio", at: 705, span: 30, colour: "#f59e0b", quote: "…around midday…" },
];

export function EventDemo() {
  const [confirmed, setConfirmed] = useState(false);
  const [alt, setAlt] = useState(false);
  const lo = 600;
  const hi = 780;
  const x = (m: number) => `${((m - lo) / (hi - lo)) * 100}%`;
  const hm = (m: number) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
  return (
    <div className="rounded-2xl border border-white/10 bg-navy-900/70 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Proposed event · fictional</p>
          <p className="font-medium text-slate-50">Arrival — “the truck” on 12 Oct</p>
          <p className="text-xs text-slate-500">
            3 accounts · linked only by the word “truck” · association 0.35 (heuristic: weak link, the witness
            states no date)
          </p>
        </div>
        <button
          type="button"
          onClick={() => setConfirmed((v) => !v)}
          aria-pressed={confirmed}
          className={clsx(
            "inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm transition-colors",
            confirmed ? "border-processed/50 bg-processed/10 text-processed" : "border-sky-500/40 bg-sky-500/10 text-sky-200 hover:bg-sky-500/20",
          )}
        >
          <Check className="h-4 w-4" aria-hidden />
          {confirmed ? "Confirmed by reviewer" : "Reviewer: confirm same occurrence"}
        </button>
      </div>

      <div className="mt-5">
        <div className="relative h-24 rounded-xl border border-navy-800 bg-navy-950/70">
          {[630, 660, 690, 720, 750].map((t) => (
            <span key={t} className="absolute bottom-0 top-0 w-px bg-navy-800" style={{ left: x(t) }}>
              <span className="absolute -bottom-5 -translate-x-1/2 text-[10px] tabular-nums text-slate-600">{hm(t)}</span>
            </span>
          ))}
          {ACCOUNTS.map((a, i) => (
            <div key={a.label} className="absolute flex items-center" style={{ left: x(a.at), top: `${14 + i * 24}px` }}>
              <span
                className="h-3 rounded-full border"
                style={{
                  width: a.span ? `calc(${x(a.at + a.span)} - ${x(a.at)})` : "12px",
                  marginLeft: a.span ? 0 : "-6px",
                  background: `${a.colour}55`,
                  borderColor: a.colour,
                  minWidth: 12,
                }}
              />
              <span className="ml-2 whitespace-nowrap text-[11px] text-slate-300">{a.label}</span>
            </div>
          ))}
        </div>
      </div>

      <ul className="mt-8 grid gap-2 md:grid-cols-2">
        <li className="rounded-lg border border-processed/30 bg-processed/5 p-3 text-xs">
          <span className="font-medium text-processed">Within tolerance</span>
          <span className="text-slate-400"> · receipt 10:30 vs gate 10:32 (2 min)</span>
        </li>
        <li
          className={clsx(
            "rounded-lg border p-3 text-xs transition-colors",
            confirmed ? "border-inconsistency/50 bg-inconsistency/10" : "border-navy-800 bg-navy-950/60",
          )}
        >
          <span className={clsx("font-medium", confirmed ? "text-inconsistency" : "text-slate-300")}>
            {confirmed ? "⚠ Possible inconsistency (for review)" : "Differs · compared only after confirmation"}
          </span>
          <span className="text-slate-400"> · receipt 10:30 vs witness ≈11:45–12:15</span>
        </li>
      </ul>

      {confirmed && (
        <div className="evx-page mt-3 rounded-lg border border-white/10 bg-navy-950/60">
          <button
            type="button"
            onClick={() => setAlt((v) => !v)}
            aria-expanded={alt}
            className="flex w-full items-center justify-between px-3 py-2 text-left text-sm text-slate-200"
          >
            Alternative explanations (3)
            <ChevronDown className={clsx("h-4 w-4 transition-transform", alt && "rotate-180")} aria-hidden />
          </button>
          {alt && (
            <ul className="space-y-1.5 border-t border-white/5 px-3 py-2 text-xs text-slate-400">
              <li>• The witness is estimating (“around”) and may be recalling a different moment.</li>
              <li>• There may have been two visits that day; check the gate log for a second entry.</li>
              <li>• A clock on one device may be set differently. No time zone is stated.</li>
              <li className="pt-1 text-slate-500">EvidenceX does not decide which account is correct.</li>
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

// --- G. graph demo --------------------------------------------------------------------

const G_NODES = [
  { id: "e1", kind: "evidence", label: "receipt.pdf", x: 80, y: 70 },
  { id: "e2", kind: "evidence", label: "gate.jpg", x: 80, y: 190 },
  { id: "e3", kind: "evidence", label: "call.m4a", x: 80, y: 310 },
  { id: "n1", kind: "entity", label: "KX-4471", x: 280, y: 120 },
  { id: "n2", kind: "entity", label: "NS-88421", x: 280, y: 260 },
  { id: "v1", kind: "event", label: "Arrival 12 Oct", x: 460, y: 190 },
  { id: "c1", kind: "conflict", label: "10:30 vs ≈noon", x: 600, y: 300 },
  { id: "n3", kind: "entity", label: "Warehouse A", x: 600, y: 80 },
];
const G_EDGES: [string, string][] = [
  ["e1", "n1"], ["e2", "n1"], ["e1", "n2"], ["e3", "n2"], ["n1", "v1"], ["n2", "v1"],
  ["e3", "v1"], ["v1", "c1"], ["e1", "c1"], ["e3", "c1"], ["v1", "n3"], ["e1", "n3"],
];
const G_STYLE: Record<string, { fill: string; stroke: string; r: number }> = {
  evidence: { fill: "#1f2f4a", stroke: "#94a3b8", r: 18 },
  entity: { fill: "#0e7490", stroke: "#67e8f9", r: 14 },
  event: { fill: "#312e81", stroke: "#a5b4fc", r: 18 },
  conflict: { fill: "#78350f", stroke: "#f59e0b", r: 14 },
};

export function GraphDemo() {
  const [focus, setFocus] = useState<string | null>("v1");
  const near = useMemo(() => {
    const s = new Set<string>();
    if (!focus) return s;
    s.add(focus);
    for (const [a, b] of G_EDGES) {
      if (a === focus) s.add(b);
      if (b === focus) s.add(a);
    }
    return s;
  }, [focus]);
  const pos = new Map(G_NODES.map((n) => [n.id, n]));
  return (
    <div className="overflow-hidden rounded-2xl border border-white/10 bg-[#0b1220]">
      <svg viewBox="0 0 700 380" className="block h-auto w-full" role="img" aria-label="Example knowledge graph (fictional): select a node to highlight its connections">
        {G_EDGES.map(([a, b]) => {
          const p = pos.get(a)!;
          const q = pos.get(b)!;
          const on = focus && near.has(a) && near.has(b);
          const amber = b === "c1";
          return (
            <line
              key={a + b}
              x1={p.x}
              y1={p.y}
              x2={q.x}
              y2={q.y}
              stroke={amber ? "#f59e0b" : on ? "#7dd3fc" : "#334155"}
              strokeWidth={on ? 2 : 1}
              opacity={focus && !on ? 0.2 : 0.9}
              style={{ transition: "all 200ms" }}
            />
          );
        })}
        {G_NODES.map((n) => {
          const s = G_STYLE[n.kind];
          const dim = focus !== null && !near.has(n.id);
          return (
            <g
              key={n.id}
              transform={`translate(${n.x} ${n.y})`}
              tabIndex={0}
              role="button"
              aria-label={`${n.kind}: ${n.label}`}
              aria-pressed={focus === n.id}
              onMouseEnter={() => setFocus(n.id)}
              onFocus={() => setFocus(n.id)}
              onClick={() => setFocus(n.id)}
              className="cursor-pointer outline-none"
              style={{ opacity: dim ? 0.3 : 1, transition: "opacity 200ms" }}
            >
              {focus === n.id && <circle r={s.r + 12} fill={s.stroke} opacity="0.15" />}
              {n.kind === "conflict" ? (
                <rect x={-s.r} y={-s.r} width={s.r * 2} height={s.r * 2} transform="rotate(45)" fill={s.fill} stroke={s.stroke} strokeWidth="1.5" />
              ) : n.kind === "evidence" ? (
                <rect x={-s.r} y={-s.r * 0.75} width={s.r * 2} height={s.r * 1.5} rx="4" fill={s.fill} stroke={s.stroke} strokeWidth="1.5" />
              ) : (
                <circle r={s.r} fill={s.fill} stroke={s.stroke} strokeWidth="1.5" />
              )}
              <text y={s.r + 16} textAnchor="middle" className="fill-slate-300 text-[11px]" style={{ paintOrder: "stroke", stroke: "#0b1220", strokeWidth: 3 }}>
                {n.label}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="flex flex-wrap gap-4 border-t border-white/5 px-4 py-2.5 text-[11px] text-slate-400">
        {[
          ["Evidence", G_STYLE.evidence.stroke],
          ["Entity", G_STYLE.entity.stroke],
          ["Event", G_STYLE.event.stroke],
          ["Possible inconsistency", G_STYLE.conflict.stroke],
        ].map(([l, c]) => (
          <span key={l} className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full border" style={{ borderColor: c }} aria-hidden /> {l}
          </span>
        ))}
        <span className="ml-auto inline-flex items-center gap-1 text-slate-500">
          <Network className="h-3.5 w-3.5" aria-hidden /> fictional example · exportable as JSON / GraphML
        </span>
      </div>
    </div>
  );
}

export function TrustBadge() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-xs text-slate-300">
      <ShieldCheck className="h-3.5 w-3.5 text-processed" aria-hidden /> Surfaces and organizes. People decide.
    </span>
  );
}
