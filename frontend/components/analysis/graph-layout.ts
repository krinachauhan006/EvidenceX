// Deterministic force-directed layout for the knowledge graph. Pure: no React, no
// randomness (initial positions come from a hash of each node id), so the same graph
// always gets the same picture and tests can check it.

export interface LayoutNode {
  id: string;
  kind: string;
}

export interface LayoutEdge {
  source: string;
  target: string;
}

export interface Point {
  x: number;
  y: number;
}

export interface LayoutOptions {
  width?: number;
  height?: number;
  iterations?: number;
}

/** FNV-1a 32-bit hash, for stable pseudo-random starting angles. */
export function hashString(value: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < value.length; i += 1) {
    h ^= value.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

// Start each kind on its own ring so the picture settles quickly and readably.
const RING: Record<string, number> = { evidence: 0.15, entity: 0.45, claim: 0.75, contradiction: 0.6 };

export function layoutGraph(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  options: LayoutOptions = {},
): Map<string, Point> {
  const width = options.width ?? 1200;
  const height = options.height ?? 800;
  const iterations = options.iterations ?? 220;
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) / 2;
  const pos = new Map<string, Point>();
  const ordered = [...nodes].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));

  for (const n of ordered) {
    const h = hashString(n.id);
    const angle = ((h % 3600) / 3600) * Math.PI * 2;
    const r = radius * (RING[n.kind] ?? 0.5) * (0.85 + ((h >>> 12) % 100) / 400);
    pos.set(n.id, { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) });
  }
  if (ordered.length <= 1) {
    for (const n of ordered) pos.set(n.id, { x: cx, y: cy });
    return pos;
  }

  // Sorted so floating-point sums happen in the same order for any input order.
  const key = (e: LayoutEdge) => `${e.source}\u0000${e.target}`;
  const links = edges
    .filter((e) => pos.has(e.source) && pos.has(e.target) && e.source !== e.target)
    .sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0));
  const area = width * height;
  // Ideal edge length. Capped so small graphs stay near the centre instead of being
  // pushed against the canvas edges.
  const k = Math.min(Math.sqrt(area / ordered.length) * 0.75, Math.min(width, height) / 5);
  let temperature = width / 10;
  const cooling = temperature / (iterations + 1);

  for (let step = 0; step < iterations; step += 1) {
    const disp = new Map<string, Point>(ordered.map((n) => [n.id, { x: 0, y: 0 }]));
    // Repulsion between every pair.
    for (let i = 0; i < ordered.length; i += 1) {
      const a = pos.get(ordered[i].id)!;
      const da = disp.get(ordered[i].id)!;
      for (let j = i + 1; j < ordered.length; j += 1) {
        const b = pos.get(ordered[j].id)!;
        const db = disp.get(ordered[j].id)!;
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let dist = Math.hypot(dx, dy);
        if (dist < 0.01) {
          // Coincident points: separate along a fixed, id-derived direction.
          dx = ((hashString(ordered[i].id + ordered[j].id) % 200) - 100) / 100 || 0.5;
          dy = 0.5;
          dist = Math.hypot(dx, dy);
        }
        const force = (k * k) / dist;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        da.x += fx;
        da.y += fy;
        db.x -= fx;
        db.y -= fy;
      }
    }
    // Attraction along edges.
    for (const e of links) {
      const a = pos.get(e.source)!;
      const b = pos.get(e.target)!;
      const dx = a.x - b.x;
      const dy = a.y - b.y;
      const dist = Math.max(Math.hypot(dx, dy), 0.01);
      const force = (dist * dist) / k;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      disp.get(e.source)!.x -= fx;
      disp.get(e.source)!.y -= fy;
      disp.get(e.target)!.x += fx;
      disp.get(e.target)!.y += fy;
    }
    // Move, limited by the temperature, with a gentle pull to the centre.
    for (const n of ordered) {
      const p = pos.get(n.id)!;
      const d = disp.get(n.id)!;
      d.x += (cx - p.x) * 0.02 * k / 10;
      d.y += (cy - p.y) * 0.02 * k / 10;
      const len = Math.max(Math.hypot(d.x, d.y), 0.01);
      const move = Math.min(len, temperature);
      p.x = Math.min(width - 20, Math.max(20, p.x + (d.x / len) * move));
      p.y = Math.min(height - 20, Math.max(20, p.y + (d.y / len) * move));
    }
    temperature = Math.max(temperature - cooling, 0.5);
  }
  return pos;
}

/** Ids of the selected node and its direct neighbours, for highlighting. */
export function neighbourhood(id: string | null, edges: LayoutEdge[]): Set<string> {
  const out = new Set<string>();
  if (!id) return out;
  out.add(id);
  for (const e of edges) {
    if (e.source === id) out.add(e.target);
    if (e.target === id) out.add(e.source);
  }
  return out;
}

/** Zoom by `factor` around a screen point, keeping that point fixed. */
export function zoomAt(
  view: { x: number; y: number; scale: number },
  factor: number,
  at: Point,
  limits: { min: number; max: number } = { min: 0.2, max: 4 },
): { x: number; y: number; scale: number } {
  const scale = Math.min(limits.max, Math.max(limits.min, view.scale * factor));
  const applied = scale / view.scale;
  return { scale, x: at.x - (at.x - view.x) * applied, y: at.y - (at.y - view.y) * applied };
}
