// Tests for the pure analysis helpers (graph layout, source links, review labels).
// Run: node --experimental-strip-types --no-warnings --test tests/analysis-helpers.test.mjs

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  hashString,
  layoutGraph,
  neighbourhood,
  zoomAt,
} from "../components/analysis/graph-layout.ts";
import { bboxPercent, parseFocus, sourceHref } from "../components/analysis/source-link.ts";
import {
  claimActions,
  contradictionActions,
  contradictionStatus,
  eventTimeLabel,
  methodLabel,
  percent,
} from "../components/analysis/review-labels.ts";

const nodes = [
  { id: "evidence:1", kind: "evidence" },
  { id: "evidence:2", kind: "evidence" },
  { id: "entity:a", kind: "entity" },
  { id: "claim:x", kind: "claim" },
  { id: "claim:y", kind: "claim" },
  { id: "contradiction:c", kind: "contradiction" },
];
const edges = [
  { source: "evidence:1", target: "claim:x" },
  { source: "evidence:2", target: "claim:y" },
  { source: "claim:x", target: "entity:a" },
  { source: "claim:y", target: "entity:a" },
  { source: "contradiction:c", target: "claim:x" },
  { source: "contradiction:c", target: "claim:y" },
];

test("layout is deterministic and independent of input order", () => {
  const a = layoutGraph(nodes, edges, { width: 800, height: 600 });
  const b = layoutGraph([...nodes].reverse(), [...edges].reverse(), { width: 800, height: 600 });
  for (const n of nodes) assert.deepEqual(a.get(n.id), b.get(n.id));
});

test("layout keeps every node inside the canvas and apart", () => {
  const pos = layoutGraph(nodes, edges, { width: 800, height: 600 });
  assert.equal(pos.size, nodes.length);
  const points = [...pos.values()];
  for (const p of points) {
    assert.ok(p.x >= 20 && p.x <= 780 && p.y >= 20 && p.y <= 580, JSON.stringify(p));
  }
  for (let i = 0; i < points.length; i += 1) {
    for (let j = i + 1; j < points.length; j += 1) {
      assert.ok(Math.hypot(points[i].x - points[j].x, points[i].y - points[j].y) > 5);
    }
  }
});

test("small graphs are not pushed against the canvas edges", () => {
  const pos = layoutGraph(nodes, edges, { width: 800, height: 600 });
  const onEdge = [...pos.values()].filter((p) => p.x <= 20 || p.x >= 780 || p.y <= 20 || p.y >= 580);
  assert.equal(onEdge.length, 0, JSON.stringify([...pos.entries()]));
});

test("connected nodes end up closer than unconnected ones on average", () => {
  const pos = layoutGraph(nodes, edges, { width: 800, height: 600 });
  const d = (a, b) => Math.hypot(pos.get(a).x - pos.get(b).x, pos.get(a).y - pos.get(b).y);
  assert.ok(d("evidence:1", "claim:x") < d("evidence:1", "evidence:2") + 1);
});

test("edges to unknown nodes are ignored; tiny graphs are centred", () => {
  const pos = layoutGraph([{ id: "only", kind: "entity" }], [{ source: "only", target: "ghost" }], {
    width: 100,
    height: 100,
  });
  assert.deepEqual(pos.get("only"), { x: 50, y: 50 });
  assert.equal(layoutGraph([], []).size, 0);
});

test("hash and neighbourhood helpers", () => {
  assert.equal(hashString("abc"), hashString("abc"));
  assert.notEqual(hashString("abc"), hashString("abd"));
  assert.deepEqual([...neighbourhood("claim:x", edges)].sort(), [
    "claim:x",
    "contradiction:c",
    "entity:a",
    "evidence:1",
  ]);
  assert.equal(neighbourhood(null, edges).size, 0);
});

test("zoom keeps the pointer position fixed and respects limits", () => {
  const v = zoomAt({ x: 0, y: 0, scale: 1 }, 2, { x: 100, y: 50 });
  assert.deepEqual(v, { scale: 2, x: -100, y: -50 });
  assert.equal(zoomAt({ x: 0, y: 0, scale: 3.9 }, 2, { x: 0, y: 0 }).scale, 4);
  assert.equal(zoomAt({ x: 0, y: 0, scale: 0.25 }, 0.1, { x: 0, y: 0 }).scale, 0.2);
});

test("source links carry segment, page and audio time", () => {
  const href = sourceHref("case-1", {
    evidenceId: "ev-1",
    segmentId: "11111111-2222-3333-4444-555555555555",
    locator: { kind: "audio", start: 12.34, end: 15, word_start: 12.81 },
  });
  assert.ok(href.startsWith("/cases/case-1/evidence/ev-1?"));
  const params = new URL(`http://x${href}`).searchParams;
  assert.equal(params.get("tab"), "preview");
  assert.equal(params.get("t"), "12.8");
  const pdf = new URL(
    `http://x${sourceHref("c", { evidenceId: "e", segmentId: null, locator: { kind: "pdf", page: 3 } })}`,
  ).searchParams;
  assert.equal(pdf.get("page"), "3");
  assert.equal(pdf.get("segment"), null);
});

test("focus parsing ignores invalid values", () => {
  const p = new URLSearchParams("tab=preview&segment=11111111-2222&page=2&t=4.5");
  assert.deepEqual(parseFocus((k) => p.get(k)), {
    tab: "preview",
    segmentId: "11111111-2222",
    claimId: null,
    page: 2,
    t: 4.5,
  });
  const bad = new URLSearchParams("tab=evil&segment=<script>&page=-1&t=abc");
  assert.deepEqual(parseFocus((k) => bad.get(k)), {
    tab: "overview",
    segmentId: null,
    claimId: null,
    page: null,
    t: null,
  });
});

test("bounding boxes become clamped percentages, or null", () => {
  assert.deepEqual(bboxPercent([10, 20, 60, 70], 100, 200), {
    left: 10,
    top: 10,
    width: 50,
    height: 25,
  });
  assert.equal(bboxPercent([1, 2, 3], 100, 100), null);
  assert.equal(bboxPercent([10, 10, 5, 5], 100, 100), null);
  assert.equal(bboxPercent([0, 0, 1, 1], 0, 100), null);
});

test("review actions mirror the server transitions", () => {
  assert.deepEqual(claimActions("unreviewed"), ["verify", "needs_verification", "reject"]);
  assert.deepEqual(claimActions("verified"), ["needs_verification"]);
  assert.deepEqual(contradictionActions("unreviewed"), ["confirm", "unresolved", "reject"]);
  assert.deepEqual(contradictionActions("resolved"), ["unresolved"]);
  assert.deepEqual(claimActions("bogus"), []);
});

test("labels never overstate certainty", () => {
  assert.equal(eventTimeLabel({ raw: "1030", precision: "unknown" }), '"1030" (ambiguous; not interpreted)');
  assert.equal(
    eventTimeLabel({ raw: "after noon", precision: "range", range: [720, 1439] }),
    '"after noon" (approximate: 12:00–23:59)',
  );
  assert.equal(eventTimeLabel(null), null);
  assert.equal(percent(null), "not reported");
  assert.equal(percent(0.624), "62%");
  assert.match(methodLabel("rule_based_v1"), /not AI/);
  assert.equal(contradictionStatus("confirmed").label, "Inconsistency confirmed");
});
