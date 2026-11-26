// Phase 2 frontend: pure helpers and source contracts for auth, landing page,
// accessibility of motion, video locators and event comparison labels.
// Run: node --experimental-strip-types --no-warnings --test tests/phase2-ui.test.mjs
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { safeNext } from "../lib/safe-next.ts";
import {
  axisBounds,
  claimInterval,
  comparisonLabel,
  eventStatusTone,
  hhmm,
} from "../components/events/event-labels.ts";
import { describeLocator, segmentTypeLabel } from "../components/evidence/source-reference.ts";
import { sourceHref } from "../components/analysis/source-link.ts";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = (p) => readFileSync(join(ROOT, p), "utf8");

// --- auth ---------------------------------------------------------------------------

test("post-login redirects accept only same-site relative paths", () => {
  assert.equal(safeNext("/cases/abc?tab=x"), "/cases/abc?tab=x");
  for (const bad of [null, "", "https://evil.example", "//evil.example", "/\\evil", "javascript:alert(1)"]) {
    assert.equal(safeNext(bad), "/cases", String(bad));
  }
  assert.equal(safeNext("/login?next=/x"), "/cases");
  assert.equal(safeNext("/register"), "/cases");
  assert.equal(safeNext("/loginx"), "/loginx"); // only the exact auth pages are refused
});

test("every API call sends the session cookie and no token is stored in script", () => {
  const client = src("lib/api/client.ts");
  assert.match(client, /credentials: "include"/);
  assert.match(client, /xhr\.withCredentials = true/);
  assert.match(client, /status === 401/);
  for (const f of ["lib/api/client.ts", "lib/api/auth.ts", "components/auth/auth-provider.tsx", "components/auth/auth-form.tsx"]) {
    assert.doesNotMatch(src(f), /localStorage|sessionStorage|document\.cookie/, f);
  }
  // Components never call fetch directly; only the typed client does.
  for (const f of [
    "components/workspace/video-viewer.tsx",
    "app/(dashboard)/cases/[caseId]/reports/page.tsx",
    "app/(dashboard)/cases/[caseId]/search/page.tsx",
  ]) {
    assert.doesNotMatch(src(f), /\bfetch\(/, f);
  }
});

test("the self-declared reviewer name is gone; the API attributes actions", () => {
  assert.doesNotMatch(src("components/cases/case-shell.tsx"), /Reviewer name recorded/);
  assert.doesNotMatch(src("hooks/use-reviewer.ts"), /localStorage/);
});

test("the signed-in area is gated and role-aware", () => {
  assert.match(src("app/(dashboard)/layout.tsx"), /AppShell/);
  assert.match(src("components/layout/app-shell.tsx"), /<AuthGate>/);
  const shell = src("components/cases/case-shell.tsx");
  assert.match(shell, /hasRole\(role, "owner"\)/);
  assert.match(shell, /readOnly=\{!canEdit\}/);
});

// --- landing page ----------------------------------------------------------------------

test("/ is the public landing page with the required copy and CTAs", () => {
  const page = src("app/page.tsx");
  assert.doesNotMatch(page, /redirect\(/);
  assert.match(page, /Evidence doesn&apos;t exist in isolation\./);
  assert.match(page, /Neither should your investigation\./);
  assert.match(page, /Explore How It Works/);
  assert.match(src("components/landing/interactive.tsx"), /Start an Investigation/);
  assert.match(page, /id="how-it-works"/);
  assert.match(page, /fictional/i);
  // Truthful copy: no invented metrics or testimonials, explicit limits.
  assert.doesNotMatch(page, /testimonial|trusted by|\b\d+% (faster|more)\b|customers/i);
  assert.match(page, /does not determine guilt/i);
});

test("landing copy never claims to detect lies or authenticate", () => {
  // The explicit "It does not" list is the one place these words are allowed.
  const page = src("app/page.tsx").replace(/const DOES_NOT = \[[\s\S]*?\];/, "");
  const text = page + src("components/landing/interactive.tsx") + src("components/landing/hero-visual.tsx");
  const banned = /\b(detects? (lies|deception)|proves?|authenticat\w*|guilt\w*|lie detector)\b/i;
  for (const line of text.split("\n")) {
    if (banned.test(line)) assert.match(line, /\b(not|never|n't)\b/i, line.trim());
  }
});

test("motion respects reduced-motion and persistent animation can be paused", () => {
  const css = src("app/globals.css");
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /\.evx-paused/);
  assert.match(css, /@supports \(animation-timeline: view\(\)\)/); // reveal only where supported
  const hero = src("components/landing/hero-visual.tsx");
  assert.match(hero, /Pause animation/);
  assert.match(hero, /prefers-reduced-motion/);
  assert.match(hero, /aria-pressed=\{paused\}/);
});

test("login and register pages exist", () => {
  assert.ok(existsSync(join(ROOT, "app", "login", "page.tsx")));
  assert.ok(existsSync(join(ROOT, "app", "register", "page.tsx")));
});

test("every new case section has a page", () => {
  for (const s of ["events", "timeline", "search", "reports", "audit", "settings"]) {
    assert.ok(existsSync(join(ROOT, "app", "(dashboard)", "cases", "[caseId]", s, "page.tsx")), s);
  }
});

// --- video ------------------------------------------------------------------------------

test("video locators read as frame times with their region", () => {
  const ref = describeLocator({ kind: "video", t: 72.3, frame_width: 640, frame_height: 360, bbox: [10, 20, 110, 40], unit: "px" });
  assert.equal(ref.available, true);
  assert.equal(ref.label, "Frame at 00:01:12.3");
  assert.match(ref.detail, /Text region \[10, 20, 110, 40\] px/);
  assert.equal(segmentTypeLabel("video_ocr_line"), "Text on a video frame");
  const href = sourceHref("c1", { evidenceId: "e1", segmentId: "s1", locator: { kind: "video", t: 4.2 } });
  assert.match(href, /[?&]t=4\.2(&|$)/);
});

// --- events -----------------------------------------------------------------------------

test("comparison labels never call a missing time a conflict", () => {
  assert.equal(comparisonLabel("missing_time").tone, "neutral");
  assert.equal(comparisonLabel("different_day").tone, "neutral");
  assert.equal(comparisonLabel("within_tolerance").tone, "green");
  assert.equal(comparisonLabel("conflict_candidate").tone, "amber");
  assert.match(comparisonLabel("conflict_candidate").help, /not a finding of fact/);
  assert.equal(comparisonLabel("something_new").label, "something new");
  assert.equal(eventStatusTone("confirmed"), "green");
});

test("time helpers keep the source's precision", () => {
  assert.deepEqual(claimInterval({ minutes: 630, range: null }), [630, 630]);
  assert.deepEqual(claimInterval({ minutes: null, range: [690, 720] }), [690, 720]);
  assert.equal(claimInterval({ raw: "1030", precision: "unknown" }), null);
  assert.equal(claimInterval(null), null);
  assert.equal(hhmm(630), "10:30");
  assert.equal(hhmm(1440), "00:00");
  const [lo, hi] = axisBounds([[630, 630], [735, 735]]);
  assert.ok(lo < 630 && hi > 735 && lo >= 0 && hi <= 1440);
  const [a, b] = axisBounds([[630, 630]]);
  assert.ok(b - a >= 60);
  assert.deepEqual(axisBounds([]), [0, 1440]);
});

// --- fixes found in browser acceptance ---------------------------------------------------

test("hidden tooltips take no layout space (no horizontal overflow near edges)", () => {
  const prim = src("components/ui/primitives.tsx");
  const tip = prim.slice(prim.indexOf("export function InfoTip"));
  assert.match(tip, /role="tooltip"[\s\S]*?\bhidden\b[\s\S]*?group-hover:block/);
  assert.doesNotMatch(tip, /opacity-0/);
  assert.match(tip, /max-w-\[min\(16rem,80vw\)\]/);
});

test("the events page opens on All when nothing awaits review", () => {
  const page = src("app/(dashboard)/cases/[caseId]/events/page.tsx");
  assert.match(page, /some\(\(e\) => e\.status === "proposed"\) \? "proposed" : "all"/);
  assert.match(page, /setChosen\(true\)/); // a user's own tab choice is not overridden
});

test("the video viewer shows the first sampled frame once segments load", () => {
  const v = src("components/workspace/video-viewer.tsx");
  assert.match(v, /if \(frameT === null && firstFrameT !== null\) setFrameT\(firstFrameT\)/);
});

test("the inconsistencies page describes both ways findings arise", () => {
  const p = src("app/(dashboard)/cases/[caseId]/contradictions/page.tsx");
  assert.match(p, /same identifier, or a reviewer confirmed they describe one event/);
});
