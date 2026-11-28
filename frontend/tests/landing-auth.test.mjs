// Landing page + authentication refinements: password policy, show/hide toggle,
// sticky header, readable (never faded) content, hero sequence, motion controls and
// landing images.
// Run: node --experimental-strip-types --no-warnings --test tests/landing-auth.test.mjs
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { PASSWORD_MAX, PASSWORD_MIN, passwordLength, passwordProblem } from "../lib/password-policy.ts";
import { FINAL_STEP, HERO_STEPS, initialStep, msToNext, shown, stepAt } from "../components/landing/hero-sequence.ts";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = (p) => readFileSync(join(ROOT, p), "utf8");

// --- password policy (mirrors backend security.password_problem) -----------------------

test("password minimum is 8 and matches the backend constant", () => {
  assert.equal(PASSWORD_MIN, 8);
  assert.equal(PASSWORD_MAX, 256);
  const backend = readFileSync(join(ROOT, "..", "backend", "app", "modules", "auth", "security.py"), "utf8");
  assert.match(backend, /^MIN_PASSWORD = 8$/m);
  assert.match(backend, /^MAX_PASSWORD = 256$/m);
});

test("7 characters are rejected, 8 and longer are accepted", () => {
  assert.equal(passwordProblem("abcdefg"), "The password must have at least 8 characters.");
  assert.equal(passwordProblem(""), "The password must have at least 8 characters.");
  assert.equal(passwordProblem("abcdefgh"), null);
  assert.equal(passwordProblem("a much longer passphrase"), null);
  assert.equal(passwordProblem("a".repeat(256)), null);
  assert.match(passwordProblem("a".repeat(257)), /at most 256/);
});

test("length counts Unicode code points like Python len()", () => {
  assert.equal("🔒".length, 2); // UTF-16 units
  assert.equal(passwordLength("🔒"), 1);
  assert.equal(passwordProblem("🔒".repeat(7)), "The password must have at least 8 characters.");
  assert.equal(passwordProblem("🔒".repeat(8)), null);
  assert.equal(passwordProblem("pässwörd"), null);
  assert.notEqual(passwordProblem("pässwör"), null);
});

test("leading or trailing spaces are refused, as on the server", () => {
  assert.match(passwordProblem(" abcdefgh"), /spaces/);
  assert.match(passwordProblem("abcdefgh "), /spaces/);
  assert.match(passwordProblem("        "), /spaces/);
});

test("the register form shows 8, not 10, and validates before sending", () => {
  const form = src("components/auth/auth-form.tsx");
  assert.doesNotMatch(form, /10 characters/);
  assert.match(form, /At least \{PASSWORD_MIN\} characters\./);
  assert.match(form, /passwordProblem\(password\)/);
  assert.match(form, /if \(problem\) return;/);
});

// --- show / hide password ----------------------------------------------------------------

test("the password toggle is a real, labelled, non-submitting button", () => {
  const f = src("components/auth/password-field.tsx");
  assert.match(f, /<button\s+type="button"/);
  assert.match(f, /aria-label=\{revealed \? "Hide password" : "Show password"\}/);
  assert.match(f, /aria-pressed=\{revealed\}/);
  assert.match(f, /aria-controls=\{id\}/);
  assert.match(f, /type=\{revealed \? "text" : "password"\}/);
  // Only the type changes: the controlled value and autocomplete hint are untouched.
  assert.match(f, /value=\{value\}/);
  assert.match(f, /autoComplete=\{autoComplete\}/);
  // A mouse press keeps focus (and the caret) in the input so typing continues.
  assert.match(f, /onMouseDown=\{\(e\) => e\.preventDefault\(\)\}/);
  assert.match(f, /from "lucide-react"/); // existing icon library, no new dependency
});

test("both sign-in and registration use the same password field", () => {
  const form = src("components/auth/auth-form.tsx");
  assert.match(form, /<PasswordField/);
  assert.match(form, /mode === "login" \? "current-password" : "new-password"/);
  assert.doesNotMatch(form, /type="password"/);
  assert.match(form, /setRevealed\(false\)/); // hidden again on submit
  const pkg = JSON.parse(src("package.json"));
  assert.ok(pkg.dependencies["lucide-react"]);
});

// --- sticky header -----------------------------------------------------------------------

test("the landing header is sticky and nothing above it breaks stickiness", () => {
  const nav = src("components/landing/interactive.tsx");
  assert.match(nav, /"sticky top-0 z-50/);
  assert.match(nav, /backdrop-blur-md/);
  assert.match(nav, /aria-controls="landing-mobile-menu"/);
  assert.match(nav, /e\.key === "Escape"/);
  const page = src("app/page.tsx");
  // overflow-x-hidden on an ancestor makes it a scroll container and disables sticky.
  assert.doesNotMatch(page, /overflow-x-hidden/);
  assert.match(page, /overflow-x-clip/);
  // Anchors land below the header.
  assert.match(src("app/globals.css"), /scroll-padding-top: 5\.5rem/);
});

// --- readability -------------------------------------------------------------------------

test("scroll reveal moves content but never fades it", () => {
  const css = src("app/globals.css");
  const block = css.match(/@supports \(animation-timeline: view\(\)\) \{[\s\S]*?\n\}/)[0];
  assert.match(block, /evx-drift/);
  assert.doesNotMatch(block, /evx-rise/); // evx-rise animates opacity from 0
  const drift = css.match(/@keyframes evx-drift \{[\s\S]*?\n\}/)[0];
  assert.doesNotMatch(drift, /opacity/);
});

test("landing body copy uses readable shades and text colours meet AA", () => {
  const page = src("app/page.tsx");
  assert.doesNotMatch(page, /text-slate-(500|600|700)/);
  assert.doesNotMatch(page, /opacity-\d/);
  const tw = src("tailwind.config.ts");
  assert.match(tw, /textColor: \{\s*slate: \{\s*500: "#8794aa",\s*600: "#76839a"/);
  // WCAG relative-luminance contrast of the lifted shades on navy-950 / navy-900.
  const lum = (hex) => {
    const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  };
  const ratio = (a, b) => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05);
  for (const bg of ["#0a0f1a", "#0e1524"]) {
    assert.ok(ratio("#8794aa", bg) >= 4.5, `slate-500 on ${bg}: ${ratio("#8794aa", bg)}`);
    assert.ok(ratio("#76839a", bg) >= 4.5, `slate-600 on ${bg}: ${ratio("#76839a", bg)}`);
    assert.ok(ratio("#cbd5e1", bg) >= 7, "slate-300 body copy");
  }
});

// --- hero sequence -------------------------------------------------------------------------

test("the hero story runs in the documented order and settles", () => {
  assert.deepEqual(
    HERO_STEPS.map((s) => s.phase),
    ["sources", "illuminate", "claims", "trace", "converge", "event", "inconsistency", "alternatives", "review"],
  );
  for (let i = 1; i < HERO_STEPS.length; i++) assert.ok(HERO_STEPS[i].at > HERO_STEPS[i - 1].at);
  assert.equal(stepAt(0), 0);
  assert.equal(stepAt(HERO_STEPS[3].at), 3);
  assert.equal(stepAt(HERO_STEPS[3].at - 1), 2);
  assert.equal(stepAt(1e9), FINAL_STEP);
  assert.equal(msToNext(0), HERO_STEPS[1].at);
  assert.equal(msToNext(HERO_STEPS[FINAL_STEP].at), null); // no loop: it settles
  assert.ok(HERO_STEPS[FINAL_STEP].at <= 9000, "settles within 9 s");
});

test("reduced motion starts at the complete final state", () => {
  assert.equal(initialStep(true), FINAL_STEP);
  assert.equal(initialStep(false), 0);
  for (const s of HERO_STEPS) assert.ok(shown(s.phase, FINAL_STEP), s.phase);
  assert.ok(shown("sources", 0)); // the evidence cards are visible before any motion
  assert.ok(!shown("inconsistency", 0));
});

test("hero language stays within the product's limits", () => {
  const hero = src("components/landing/hero-visual.tsx") + src("components/landing/hero-sequence.ts");
  assert.match(hero, /Possible inconsistency/);
  assert.match(hero, /Suggested event/);
  assert.match(hero, /Awaiting human review/);
  assert.match(hero, /Alternative explanations/);
  assert.doesNotMatch(hero, /\b(lie|lying|liar|deceptive|proves?|guilty|truth)\b/i);
});

test("hero controls: pause/resume, replay, keyboard and touch selection", () => {
  const hero = src("components/landing/hero-visual.tsx");
  assert.match(hero, /aria-pressed=\{paused\}/);
  assert.match(hero, /"Play animation" : "Pause animation"/);
  assert.match(hero, /Replay/);
  assert.match(hero, /prefers-reduced-motion: reduce/);
  assert.match(hero, /Animation off \(reduced motion\)/);
  assert.match(hero, /tabIndex=\{0\}/);
  assert.match(hero, /onFocus=\{\(\) => setHover\(s\.id\)\}/);
  assert.match(hero, /e\.key === "Enter" \|\| e\.key === " "/);
  assert.match(hero, /onClick=\{\(\) => setPinned/); // a tap pins a source on touch screens
  assert.match(hero, /if \(reduced \|\| paused\) return;/); // the timer stops while paused
  assert.match(src("app/globals.css"), /\.evx-paused \*,/);
});

// --- landing images ------------------------------------------------------------------------

test("every landing image file exists at every declared width", async () => {
  const photo = src("components/landing/photo.tsx");
  const block = photo.match(/export const LANDING_PHOTOS = \{([\s\S]*?)\} as const;/)[1];
  const entries = [...block.matchAll(/(\w+): \[([\d, ]+)\]/g)];
  // Exactly the images documented in LANDING_IMAGES.md (the licensing test checks
  // their documented status).
  assert.deepEqual(
    entries.map((e) => e[1]),
    ["wall", "desk", "forensic", "notebook", "corkboard", "fingerprints", "lampboard"],
  );
  for (const [, name, widths] of entries) {
    const list = widths.split(",").map((s) => Number(s.trim()));
    // Largest first: photoSrc() uses the last (smallest) width as the plain src fallback.
    assert.deepEqual(list, [...list].sort((a, b) => b - a), `${name} widths are not descending`);
    for (const w of list) {
      assert.ok(existsSync(join(ROOT, "public", "images", "landing", `${name}-${w}.webp`)), `${name}-${w}.webp`);
    }
  }
});

test("backgrounds are decorative and lazy; framed photos have alt text", () => {
  const photo = src("components/landing/photo.tsx");
  assert.match(photo, /aria-hidden className=\{clsx\("pointer-events-none absolute inset-0 -z-10/);
  assert.match(photo, /alt=""/);
  assert.match(photo, /loading=\{priority \? "eager" : "lazy"\}/);
  assert.match(photo, /object-cover/);
  const page = src("app/page.tsx");
  const framed = [...page.matchAll(/<FramedPhoto[\s\S]*?\/>/g)].map((m) => m[0]);
  assert.equal(framed.length, 2, "notebook and fingerprints are framed");
  for (const f of framed) assert.match(f, /alt="Illustrative photograph: [^"]{10,}"/);
  // Backgrounds never carry alt text of their own (decorative, aria-hidden wrapper).
  for (const m of page.matchAll(/<SectionPhoto[\s\S]*?\/>/g)) assert.doesNotMatch(m[0], /\balt=/);
  // Every photograph sits on CSS artwork that shows if the file is missing.
  for (const m of [...page.matchAll(/<(?:SectionPhoto|FramedPhoto)[\s\S]*?\/>/g)]) {
    if (!/name="wall"/.test(m[0])) assert.match(m[0], /fallback="\w+"/, m[0].slice(0, 60));
  }
  // Each photograph appears once on the page.
  const names = [...page.matchAll(/name="(\w+)"/g)].map((m) => m[1]);
  assert.equal(new Set(names).size, names.length, names.join(","));
  assert.match(page, /Photographs on this page are illustrative/);
  assert.ok(existsSync(join(ROOT, "LANDING_IMAGES.md")));
});

test("narrow screens: grids have an explicit shrinkable column and the hero has a legible layout", () => {
  // An implicit `auto` grid column grows to the widest no-wrap label and pushes text
  // off-screen (hidden by overflow-x: clip). Every responsive landing grid declares one.
  for (const f of ["app/page.tsx", "components/landing/interactive.tsx"]) {
    for (const m of src(f).matchAll(/className="([^"]*\bgrid\b[^"]*\blg:grid-cols-[^"]*)"/g)) {
      assert.match(m[1], /\bgrid-cols-1\b/, `${f}: ${m[1].slice(0, 80)}`);
    }
  }
  const hero = src("components/landing/hero-visual.tsx");
  assert.match(hero, /<figure className="relative min-w-0">/);
  assert.match(hero, /data-testid="hero-compact"/);
  assert.match(hero, /className="space-y-3 p-3 sm:hidden"/);
  assert.match(hero, /hidden h-auto w-full select-none sm:block/);
});

// --- sign-in diagnosis: pending migration, loopback host names ---------------------------

test("the sign-in page explains a pending database migration", async () => {
  const { serverNotice } = await import("../lib/server-notice.ts");
  const msg = serverNotice({
    status: "degraded",
    service: "evidencex-api",
    database: "migration_required",
    schema: { revision: "0006_analysis_not_null_ts", expected: "0007_phase2", up_to_date: false },
  });
  assert.match(msg, /needs an update before anyone can sign in or register/);
  assert.match(msg, /0006_analysis_not_null_ts/);
  assert.match(msg, /alembic upgrade head/);
  assert.equal(serverNotice({ status: "ok", service: "evidencex-api", database: "ok" }), null);
  assert.equal(serverNotice(null), null);
  const form = src("components/auth/auth-form.tsx");
  assert.match(form, /health\(c\.signal\)/);
  assert.match(form, /data-testid="server-notice"/);
  assert.match(form, /err\.status >= 500/);
});

test("without a configured API URL the browser calls the API on its own loopback name", async () => {
  const { defaultApiBase } = await import("../lib/api/client.ts");
  assert.equal(defaultApiBase("localhost"), "http://localhost:8000");
  assert.equal(defaultApiBase("127.0.0.1"), "http://127.0.0.1:8000");
  assert.equal(defaultApiBase(undefined), "http://localhost:8000"); // server-side render
  // A real host never falls back to localhost: same-origin relative URLs instead.
  assert.equal(defaultApiBase("evidencex.example.org", "https:"), "");
});

// --- hero layering ------------------------------------------------------------------------

test("the hero photo stays whole and the opaque, elevated panel sits in front of it", () => {
  const hero = src("components/landing/hero-visual.tsx");
  const panel = hero.match(/"evx-motion relative isolate[^"]*"/)[0];
  assert.match(panel, /\bbg-\[#0a1428\]/); // opaque deep blue-navy
  assert.doesNotMatch(panel, /bg-\[#0a1428\]\/\d|backdrop-blur/); // nothing bleeds through
  assert.match(panel, /border-\[#19B9FF\]\/70/); // neon-blue edge
  assert.match(hero, /0_0_14px_rgba\(25,185,255,0\.45\)/); // neon outer glow
  assert.match(hero, /inset_0_1px_0_0_rgba\(101,223,255,0\.35\)/); // bright top edge (glass)
  assert.match(hero, /0_24px_48px_-18px/); // drop shadow offset downward only
  assert.match(hero, /via-\[#65DFFF\]/); // top highlight line
  assert.match(hero, /id="hero-neon"/); // glow on the event node and selected path
  // The text column sits above the panel layer and both columns can shrink.
  const page = src("app/page.tsx");
  assert.match(page, /className="relative z-10 min-w-0" data-testid="hero-copy"/);
  assert.match(page, /lg:grid-cols-\[minmax\(0,1fr\)_minmax\(0,1\.1fr\)\] lg:gap-16/);
  // The hero backdrop is the desk photograph, drawn behind the panel, never masked,
  // loaded eagerly (it is above the fold), on the CSS desk artwork as its fallback.
  const desk = page.match(/<SectionPhoto\s+name="desk"[\s\S]*?\/>/)[0];
  assert.doesNotMatch(desk, /mask|imgClassName/i);
  assert.match(desk, /\bpriority\b/);
  assert.match(desk, /fallback="desk"/);
  // The fallback layer is drawn first; the photo is positioned so it paints above it.
  const photo = src("components/landing/photo.tsx");
  assert.ok(photo.indexOf("data-photo-fallback") < photo.indexOf('className={clsx("evx-photo relative'));
  const css = src("app/globals.css");
  const art = css.match(/\.evx-art-desk \{[^}]*\}/)[0];
  assert.doesNotMatch(art, /mask|url\(/); // gradients only, no image files
  assert.match(art, /rgba\(56, 189, 248, 0\.18\)/); // cool screen light behind the panel
});

test("the session gate keeps the full requested URL and shows the server's own explanation", () => {
  const gate = src("components/auth/auth-provider.tsx");
  assert.match(gate, /\(pathname \|\| "\/cases"\) \+ window\.location\.search/);
  assert.match(gate, /encodeURIComponent\(here\)/);
  assert.match(gate, /err\.status >= 500 && typeof err\.detail === "string"/);
  assert.equal(safeNextCheck("/cases?from=deeplink"), "/cases?from=deeplink");
});

import { safeNext as safeNextCheck } from "../lib/safe-next.ts";
