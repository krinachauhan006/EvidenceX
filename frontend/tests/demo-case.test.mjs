// The optional demo investigation entry point on the Investigations dashboard.
// Run: node --experimental-strip-types --no-warnings --test tests/demo-case.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = (p) => readFileSync(join(ROOT, p), "utf8");

test("the dashboard offers the demo, labelled as fictional", () => {
  const page = src("app/(dashboard)/cases/page.tsx");
  assert.match(page, /Explore Demo Investigation/);
  assert.match(page, /Open a preloaded fictional investigation to explore how EvidenceX organizes evidence/);
  assert.match(page, /Fictional demo data/);
  assert.match(page, /not a real investigation/);
  assert.match(page, /<DemoCard \/>/);
});

test("the client loads the demo through the authenticated API only", () => {
  const api = src("lib/api/cases.ts");
  assert.match(api, /apiFetch<DemoCase>\("\/api\/demo\/missing-shipment", \{ method: "POST" \}\)/);
  assert.match(api, /apiFetch<\{ case_id: string \| null \}>\("\/api\/demo\/missing-shipment"/);
});
