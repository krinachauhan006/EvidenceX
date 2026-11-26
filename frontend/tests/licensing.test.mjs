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

const UNVERIFIED = ["desk", "forensic", "corkboard", "notebook", "fingerprints", "lampboard"];

test("only the cleared wall-* artwork is shipped in public/images/landing", () => {
  const files = readdirSync(join(ROOT, "public", "images", "landing")).sort();
  assert.deepEqual(files, ["wall-1280.webp", "wall-1920.webp", "wall-768.webp"]);
});

test("no source file references a photograph with unverified rights", () => {
  for (const f of ["app/page.tsx", "components/landing/photo.tsx", "components/landing/backdrop.tsx",
                   "components/landing/hero-visual.tsx", "components/landing/interactive.tsx", "app/globals.css", "app/layout.tsx"]) {
    const text = src(`frontend/${f}`);
    for (const name of UNVERIFIED) {
      assert.doesNotMatch(text, new RegExp(`images/landing/${name}-|name="${name}"`), `${f} references ${name}`);
    }
  }
  const page = src("frontend/app/page.tsx");
  assert.equal([...page.matchAll(/<SectionPhoto\s+name="(\w+)"/g)].map((m) => m[1]).join(","), "wall");
  assert.doesNotMatch(page, /<FramedPhoto/);
  // The replaced sections keep a decorative backdrop instead of a photograph.
  for (const art of ["desk", "scatter", "threads", "lamp"]) assert.match(page, new RegExp(`<SectionBackdrop\\s+art="${art}"`));
  for (const kind of ["map", "ridges"]) assert.match(page, new RegExp(`<FramedArt kind="${kind}"`));
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
