// Licence notices: the public footer links to the source code and the LICENSE file, and
// the URL matches the one the backend writes into generated PDFs.
// Run: node --experimental-strip-types --no-warnings --test tests/licensing.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { LICENSE_NAME, LICENSE_URL, SOURCE_CODE_URL } from "../lib/project.ts";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const REPO = join(ROOT, "..");
const src = (p) => readFileSync(join(REPO, p), "utf8");

test("source and licence URLs point at the public repository and its root LICENSE", () => {
  assert.equal(SOURCE_CODE_URL, "https://github.com/krinachauhan006/EvidenceX");
  assert.equal(LICENSE_URL, `${SOURCE_CODE_URL}/blob/main/LICENSE`);
  assert.equal(LICENSE_NAME, "GNU AGPL-3.0");
});

test("the public footer shows visible Source Code and License links", () => {
  const page = src("frontend/app/page.tsx");
  const footer = page.slice(page.indexOf("<footer"), page.indexOf("</footer>"));
  assert.match(footer, /<a href=\{SOURCE_CODE_URL\}[^>]*>\s*Source Code\s*<\/a>/);
  assert.match(footer, /<a href=\{LICENSE_URL\}[^>]*rel="noopener noreferrer license"[^>]*>\s*License\s*<\/a>/);
  assert.match(footer, /licensed under the \{LICENSE_NAME\}/);
  assert.match(footer, /Third-party components keep their own\s+licences/);
});

test("the backend PDF notice names the same source URL", () => {
  const notice = src("backend/app/modules/analysis/pdf_notice.py");
  assert.match(notice, new RegExp(`SOURCE_CODE_URL = "${SOURCE_CODE_URL.replace(/[.]/g, "\\.")}"`));
});

test("the repository LICENSE is the GNU AGPL version 3", () => {
  const license = src("LICENSE");
  assert.match(license, /^\s+GNU AFFERO GENERAL PUBLIC LICENSE\n\s+Version 3, 19 November 2007/);
  assert.match(license, /13\. Remote Network Interaction; Use with the GNU General Public License\./);
  assert.match(license, /END OF TERMS AND CONDITIONS/);
});

// --- landing images: only cleared artwork is shipped or referenced --------------------

import { readdirSync } from "node:fs";

// Explicit allow-list of shipped landing images and their DOCUMENTED rights status.
// "cleared"      = declared cleared by the project owner (generation record exists).
// "owner-risk"   = shipped at the project owner's direction; usage rights NOT verified.
//                  This is a risk decision, not proof of ownership or permission.
// Adding an image, or changing a status, requires changing this list AND the matching
// row in LANDING_IMAGES.md in the same change.
const APPROVED = {
  wall: { status: "cleared", files: ["wall-768.webp", "wall-1280.webp", "wall-1920.webp"] },
  desk: { status: "owner-risk", files: ["desk-640.webp", "desk-960.webp", "desk-1376.webp"] },
  forensic: { status: "owner-risk", files: ["forensic-768.webp", "forensic-1280.webp", "forensic-1920.webp"] },
  notebook: { status: "owner-risk", files: ["notebook-640.webp", "notebook-1024.webp"] },
  corkboard: { status: "owner-risk", files: ["corkboard-640.webp", "corkboard-960.webp", "corkboard-1408.webp"] },
  fingerprints: { status: "owner-risk", files: ["fingerprints-480.webp", "fingerprints-720.webp"] },
  lampboard: { status: "owner-risk", files: ["lampboard-480.webp", "lampboard-736.webp"] },
};

/** The row of the "Shipped" table in LANDING_IMAGES.md for `name`, split into cells. */
function shippedRow(name) {
  const doc = src("frontend/LANDING_IMAGES.md");
  const table = doc.slice(doc.indexOf("## Shipped"), doc.indexOf("## Rights not verified"));
  const line = table.split("\n").find((l) => l.startsWith(`| \`${name}\` |`));
  return line ? line.split("|").map((c) => c.trim()) : null;
}

test("only explicitly approved and documented images are shipped in public/images/landing", () => {
  const files = readdirSync(join(ROOT, "public", "images", "landing")).sort();
  const allowed = Object.values(APPROVED).flatMap((a) => a.files).sort();
  // Any extra (undocumented) file fails, and so does a missing approved file.
  assert.deepEqual(files, allowed);
  for (const name of Object.keys(APPROVED)) assert.ok(shippedRow(name), `LANDING_IMAGES.md has no Shipped row for ${name}`);
});

test("the documented rights status matches the allow-list and never calls unverified images cleared", () => {
  const doc = src("frontend/LANDING_IMAGES.md");
  for (const [name, { status }] of Object.entries(APPROVED)) {
    const rights = shippedRow(name).at(-2); // last real cell: Rights
    if (status === "cleared") {
      assert.match(rights, /cleared/i, `${name}: ${rights}`);
    } else {
      assert.match(rights, /not verified/i, `${name}: ${rights}`);
      assert.doesNotMatch(rights, /\bcleared\b/i, `${name} must not be described as cleared`);
      // Its provenance (source and origin) is recorded in the unverified-rights table.
      const section = doc.slice(doc.indexOf("## Rights not verified"));
      assert.match(section, new RegExp(`^\\| \`${name}\` \\| [^|]{10,} \\| [^|]{10,} \\|`, "m"), `${name} provenance row`);
    }
  }
  // The risk decision is stated plainly (prose may wrap, so any whitespace between words).
  assert.match(doc, /project\s+owner's\s+direction/);
  assert.match(doc, /not\s+proof\s+of\s+copyright\s+ownership\s+or\s+permission/);
});

test("the landing page only uses approved images, each in its documented section", () => {
  const photo = src("frontend/components/landing/photo.tsx");
  const declared = [...photo.match(/export const LANDING_PHOTOS = \{([\s\S]*?)\} as const;/)[1].matchAll(/(\w+): \[/g)].map((m) => m[1]);
  assert.deepEqual(declared.sort(), Object.keys(APPROVED).sort());
  const page = src("frontend/app/page.tsx");
  const used = [...page.matchAll(/<(?:SectionPhoto|FramedPhoto)\s+name="(\w+)"/g)].map((m) => m[1]);
  assert.deepEqual(used.sort(), Object.keys(APPROVED).sort());
  // No image path is hard-coded outside photo.tsx, so nothing bypasses the allow-list.
  for (const f of ["app/page.tsx", "components/landing/backdrop.tsx", "components/landing/hero-visual.tsx",
                   "components/landing/interactive.tsx", "app/globals.css", "app/layout.tsx"]) {
    assert.doesNotMatch(src(`frontend/${f}`), /images\/landing\//, `${f} references an image file directly`);
  }
  // Placements recorded in LANDING_IMAGES.md (section data attributes in page.tsx).
  const placement = { desk: "hero", forensic: "problem", wall: "how-it-works", notebook: "events", corkboard: "graph", fingerprints: "team", lampboard: "cta" };
  for (const [name, section] of Object.entries(placement)) {
    const start = page.indexOf(`data-section="${section}"`);
    const next = page.indexOf("data-section=", start + 1);
    const body = page.slice(start, next === -1 ? undefined : next);
    assert.match(body, new RegExp(`name="${name}"`), `${name} is not in the ${section} section`);
  }
});

test("the CSS artwork uses gradients only: no external or image URLs", () => {
  const css = src("frontend/app/globals.css");
  for (const m of css.matchAll(/\.evx-art-[\w-]+(?:::(?:before|after))? \{[^}]*\}/g)) {
    assert.doesNotMatch(m[0], /url\(/, m[0].slice(0, 40));
  }
});

// --- the signed-in workspace also offers the source --------------------------------------

test("every signed-in page has visible Source Code and License links", () => {
  const links = src("frontend/components/layout/source-links.tsx");
  assert.match(links, /<a href=\{SOURCE_CODE_URL\}[^>]*>\s*Source Code\s*<\/a>/);
  assert.match(links, /<a href=\{LICENSE_URL\}[^>]*rel="noopener noreferrer license"[^>]*>\s*License\s*<\/a>/);
  const shell = src("frontend/components/layout/app-shell.tsx");
  // In the main column footer (shown at every width), not only in the md+ sidebar.
  const frame = shell.slice(shell.indexOf("function Frame"), shell.indexOf("function Sidebar"));
  assert.match(frame, /<footer[^>]*>\s*<SourceLinks/);
  assert.match(src("frontend/app/(dashboard)/layout.tsx"), /AppShell/);
});
