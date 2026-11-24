"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import clsx from "clsx";
import { Maximize2, Minus, Plus, Search } from "lucide-react";
import type { Graph, GraphNode } from "@/lib/types/analysis";
import { layoutGraph, neighbourhood, zoomAt } from "@/components/analysis/graph-layout";
import { sourceHref } from "@/components/analysis/source-link";
import { claimStatus, contradictionStatus, percent } from "@/components/analysis/review-labels";
import { sourceLabel } from "@/components/analysis/claim-card";
import { Badge, BUTTON, INPUT } from "@/components/ui/primitives";

const W = 1200;
const H = 760;

const NODE_STYLE: Record<GraphNode["kind"], { r: number; fill: string; stroke: string; label: string }> = {
  evidence: { r: 15, fill: "#1f2f4a", stroke: "#94a3b8", label: "Evidence item" },
  entity: { r: 11, fill: "#0e7490", stroke: "#67e8f9", label: "Entity" },
  claim: { r: 6, fill: "#334155", stroke: "#cbd5e1", label: "Claim" },
  contradiction: { r: 10, fill: "#78350f", stroke: "#f59e0b", label: "Potential inconsistency" },
};

const EDGE_STYLE: Record<string, { stroke: string; dash?: string; label: string }> = {
  contains: { stroke: "#2b3f61", label: "evidence contains claim" },
  mentions: { stroke: "#155e75", label: "mentions entity" },
  conflicts: { stroke: "#f59e0b", label: "potential inconsistency" },
  mentions_same_entity: { stroke: "#475569", dash: "4 4", label: "same identifier across evidence" },
};

interface View {
  x: number;
  y: number;
  scale: number;
}

export function KnowledgeGraph({ caseId, graph }: { caseId: string; graph: Graph }) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [view, setView] = useState<View>({ x: 0, y: 0, scale: 1 });
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const drag = useRef<{ x: number; y: number; view: View } | null>(null);

  const positions = useMemo(
    () => layoutGraph(graph.nodes, graph.edges, { width: W, height: H }),
    [graph],
  );
  const byId = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph]);
  const focus = neighbourhood(selected ?? hovered, graph.edges);
  const matches = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return new Set<string>();
    return new Set(graph.nodes.filter((n) => n.label.toLowerCase().includes(q)).map((n) => n.id));
  }, [graph, search]);

  useEffect(() => {
    setSelected(null);
    setView({ x: 0, y: 0, scale: 1 });
  }, [graph]);

  // Wheel zoom needs a non-passive listener to stop the page from scrolling.
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = svg.getBoundingClientRect();
      const at = { x: ((e.clientX - rect.left) / rect.width) * W, y: ((e.clientY - rect.top) / rect.height) * H };
      setView((v) => zoomAt(v, e.deltaY < 0 ? 1.15 : 1 / 1.15, at));
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, []);

  function onPointerDown(e: React.PointerEvent<SVGSVGElement>) {
    if ((e.target as Element).closest("[data-node]")) return;
    drag.current = { x: e.clientX, y: e.clientY, view };
    (e.currentTarget as SVGSVGElement).setPointerCapture(e.pointerId);
  }

  function onPointerMove(e: React.PointerEvent<SVGSVGElement>) {
    const d = drag.current;
    const svg = svgRef.current;
    if (!d || !svg) return;
    const rect = svg.getBoundingClientRect();
    setView({
      ...d.view,
      x: d.view.x + ((e.clientX - d.x) / rect.width) * W,
      y: d.view.y + ((e.clientY - d.y) / rect.height) * H,
    });
  }

  const zoom = (factor: number) => setView((v) => zoomAt(v, factor, { x: W / 2, y: H / 2 }));
  const sel = selected ? byId.get(selected) ?? null : null;
  const dim = (id: string) => focus.size > 0 && !focus.has(id);

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="relative overflow-hidden rounded-lg border border-navy-800 bg-[#0b1220]">
        <div className="absolute left-3 top-3 z-10 flex items-center gap-1.5">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-2 h-3.5 w-3.5 text-slate-500" aria-hidden />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Find a node"
              aria-label="Find a node in the graph"
              className={`${INPUT} w-48 py-1 pl-7 text-xs`}
            />
          </div>
          <button type="button" className={`${BUTTON} bg-navy-900 px-2`} onClick={() => zoom(1.25)} aria-label="Zoom in">
            <Plus className="h-3.5 w-3.5" aria-hidden />
          </button>
          <button type="button" className={`${BUTTON} bg-navy-900 px-2`} onClick={() => zoom(0.8)} aria-label="Zoom out">
            <Minus className="h-3.5 w-3.5" aria-hidden />
          </button>
          <button type="button" className={`${BUTTON} bg-navy-900 px-2`} onClick={() => setView({ x: 0, y: 0, scale: 1 })} aria-label="Reset view">
            <Maximize2 className="h-3.5 w-3.5" aria-hidden />
          </button>
        </div>
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          className="h-[38rem] w-full cursor-grab touch-none select-none active:cursor-grabbing"
          role="img"
          aria-label={`Knowledge graph with ${graph.nodes.length} nodes and ${graph.edges.length} links`}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={() => (drag.current = null)}
          onClick={(e) => {
            if (!(e.target as Element).closest("[data-node]")) setSelected(null);
          }}
        >
          <g transform={`translate(${view.x} ${view.y}) scale(${view.scale})`}>
            {graph.edges.map((e) => {
              const a = positions.get(e.source);
              const b = positions.get(e.target);
              if (!a || !b) return null;
              const style = EDGE_STYLE[e.kind] ?? EDGE_STYLE.contains;
              const faded = focus.size > 0 && !(focus.has(e.source) && focus.has(e.target));
              return (
                <line
                  key={e.id}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  stroke={style.stroke}
                  strokeWidth={e.kind === "conflicts" ? 2 : 1}
                  strokeDasharray={style.dash}
                  opacity={faded ? 0.12 : 0.85}
                />
              );
            })}
            {graph.nodes.map((n) => {
              const p = positions.get(n.id);
              if (!p) return null;
              const s = NODE_STYLE[n.kind];
              const isSel = n.id === selected;
              const showLabel = n.kind !== "claim" || isSel || n.id === hovered || matches.has(n.id);
              return (
                <g
                  key={n.id}
                  data-node
                  transform={`translate(${p.x} ${p.y})`}
                  className="cursor-pointer"
                  opacity={dim(n.id) ? 0.25 : 1}
                  onMouseEnter={() => setHovered(n.id)}
                  onMouseLeave={() => setHovered(null)}
                  onClick={() => setSelected(n.id)}
                  role="button"
                  tabIndex={0}
                  aria-label={`${s.label}: ${n.label}`}
                  onKeyDown={(ev) => {
                    if (ev.key === "Enter" || ev.key === " ") setSelected(n.id);
                  }}
                >
                  {matches.has(n.id) && <circle r={s.r + 7} fill="none" stroke="#e2e8f0" strokeDasharray="3 3" />}
                  {n.kind === "contradiction" ? (
                    <rect
                      x={-s.r}
                      y={-s.r}
                      width={s.r * 2}
                      height={s.r * 2}
                      transform="rotate(45)"
                      fill={s.fill}
                      stroke={s.stroke}
                      strokeWidth={isSel ? 3 : 1.5}
                    />
                  ) : n.kind === "evidence" ? (
                    <rect
                      x={-s.r}
                      y={-s.r * 0.75}
                      width={s.r * 2}
                      height={s.r * 1.5}
                      rx={3}
                      fill={s.fill}
                      stroke={s.stroke}
                      strokeWidth={isSel ? 3 : 1.5}
                    />
                  ) : (
                    <circle
                      r={n.kind === "entity" ? s.r + Math.min(8, Number(n.data.evidence_count ?? 0) * 1.5) : s.r}
                      fill={s.fill}
                      stroke={n.kind === "claim" && n.status === "verified" ? "#22c55e" : s.stroke}
                      strokeWidth={isSel ? 3 : 1.2}
                    />
                  )}
                  {showLabel && (
                    <text
                      y={s.r + 14}
                      textAnchor="middle"
                      className="pointer-events-none fill-slate-300 text-[11px]"
                      style={{ paintOrder: "stroke", stroke: "#0b1220", strokeWidth: 3 }}
                    >
                      {n.label.length > 32 ? `${n.label.slice(0, 31)}…` : n.label}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        </svg>
        <Legend />
        {graph.truncated && (
          <p className="absolute bottom-3 right-3 rounded bg-navy-900/90 px-2 py-1 text-[11px] text-inconsistency">
            Claims were limited for readability; use the filters to narrow the view.
          </p>
        )}
      </div>
      <SidePanel caseId={caseId} node={sel} graph={graph} onSelect={setSelected} />
    </div>
  );
}

function Legend() {
  return (
    <div className="absolute bottom-3 left-3 rounded-md border border-navy-800 bg-navy-900/90 px-3 py-2 text-[11px] text-slate-400">
      <p className="mb-1 font-medium text-slate-300">Legend</p>
      <ul className="grid grid-cols-2 gap-x-4 gap-y-0.5">
        {Object.entries(NODE_STYLE).map(([k, s]) => (
          <li key={k} className="flex items-center gap-1.5">
            <span
              className={clsx("inline-block h-2.5 w-2.5 border", k === "contradiction" ? "rotate-45" : k === "evidence" ? "rounded-sm" : "rounded-full")}
              style={{ background: s.fill, borderColor: s.stroke }}
            />
            {s.label}
          </li>
        ))}
        {Object.entries(EDGE_STYLE).map(([k, s]) => (
          <li key={k} className="flex items-center gap-1.5">
            <svg width="16" height="6" aria-hidden>
              <line x1="0" y1="3" x2="16" y2="3" stroke={s.stroke} strokeWidth="2" strokeDasharray={s.dash} />
            </svg>
            {s.label}
          </li>
        ))}
      </ul>
    </div>
  );
}

function SidePanel({
  caseId,
  node,
  graph,
  onSelect,
}: {
  caseId: string;
  node: GraphNode | null;
  graph: Graph;
  onSelect: (id: string) => void;
}) {
  if (!node) {
    return (
      <aside className="rounded-lg border border-navy-800 bg-navy-900/70 p-4 text-sm text-slate-400">
        <p className="font-medium text-slate-200">Select a node</p>
        <p className="mt-1">
          Click a node to see its details and connections. Drag to pan, scroll or use the buttons
          to zoom. Links show what the system extracted; they are not conclusions.
        </p>
        <dl className="mt-3 space-y-0.5 text-xs">
          {Object.entries(graph.counts).map(([k, v]) => (
            <div key={k} className="flex justify-between">
              <dt>{k}</dt>
              <dd className="tabular-nums text-slate-300">{v}</dd>
            </div>
          ))}
        </dl>
      </aside>
    );
  }
  const neighbours = graph.edges
    .filter((e) => e.source === node.id || e.target === node.id)
    .map((e) => ({ edge: e, other: graph.nodes.find((n) => n.id === (e.source === node.id ? e.target : e.source)) }))
    .filter((x): x is { edge: (typeof graph.edges)[number]; other: GraphNode } => Boolean(x.other));
  const root = `/cases/${caseId}`;
  const status =
    node.kind === "claim"
      ? claimStatus(node.status ?? "")
      : node.kind === "contradiction"
        ? contradictionStatus(node.status ?? "")
        : null;
  const locator = (node.data.locator ?? null) as Record<string, unknown> | null;

  return (
    <aside className="max-h-[38rem] overflow-y-auto rounded-lg border border-navy-800 bg-navy-900/70 p-4 text-sm">
      <p className="text-[11px] uppercase tracking-wider text-slate-500">{NODE_STYLE[node.kind].label}</p>
      <p className="mt-1 break-words font-medium text-slate-100">{node.label}</p>
      <div className="mt-1 flex flex-wrap gap-1">
        {node.sublabel && <Badge>{node.sublabel}</Badge>}
        {status && <Badge tone={status.tone}>{status.label}</Badge>}
        {node.kind === "contradiction" && typeof node.data.detection_confidence === "number" && (
          <Badge title="Rule match strength, not truth">detection {percent(node.data.detection_confidence)}</Badge>
        )}
      </div>
      {node.kind === "claim" && typeof node.data.quote === "string" && (
        <blockquote className="mt-2 rounded border-l-2 border-slate-500 bg-navy-950/70 px-2 py-1 font-mono text-xs text-slate-200">
          {node.data.quote}
          <span className="mt-1 block font-sans text-[11px] text-slate-500">{sourceLabel(locator)}</span>
        </blockquote>
      )}
      <div className="mt-3 flex flex-wrap gap-1.5">
        {node.kind === "evidence" && (
          <Link className={BUTTON} href={`${root}/evidence/${node.ref_id}`}>
            Open evidence workspace
          </Link>
        )}
        {node.kind === "claim" && node.evidence_id && (
          <Link
            className={BUTTON}
            href={sourceHref(caseId, {
              evidenceId: node.evidence_id,
              segmentId: typeof node.data.segment_id === "string" ? node.data.segment_id : null,
              claimId: node.ref_id,
              locator,
            })}
          >
            Show in source
          </Link>
        )}
        {node.kind === "entity" && (
          <Link className={BUTTON} href={`${root}/entities?focus=${node.ref_id}`}>
            Open entity
          </Link>
        )}
        {node.kind === "contradiction" && (
          <Link className={BUTTON} href={`${root}/contradictions`}>
            Review inconsistency
          </Link>
        )}
      </div>
      <p className="mt-4 text-xs font-medium text-slate-300">Connections ({neighbours.length})</p>
      <ul className="mt-1 space-y-1">
        {neighbours.slice(0, 60).map(({ edge, other }) => (
          <li key={edge.id}>
            <button type="button" onClick={() => onSelect(other.id)} className="w-full rounded px-1.5 py-1 text-left text-xs hover:bg-navy-800">
              <span className="text-slate-500">{(EDGE_STYLE[edge.kind] ?? EDGE_STYLE.contains).label}: </span>
              <span className="text-slate-200">{other.label}</span>
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}
