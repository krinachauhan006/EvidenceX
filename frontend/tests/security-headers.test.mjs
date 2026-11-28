// Content Security Policy and security headers for the web app (lib/csp.mjs, applied
// to every route by next.config.mjs).
// Run: node --experimental-strip-types --no-warnings --test tests/security-headers.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { MODEL_HOSTS, buildCsp, securityHeaders } from "../lib/csp.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

/** Parse "a x y; b z" into { a: ["x", "y"], b: ["z"] }. */
function directives(csp) {
  return Object.fromEntries(
    csp.split(";").map((d) => {
      const [name, ...values] = d.trim().split(/\s+/);
      return [name, values];
    }),
  );
}

test("production policy has no unsafe-eval and no websocket allowance", () => {
  const d = directives(buildCsp({ dev: false, apiBase: "" }));
  assert.ok(!d["script-src"].includes("'unsafe-eval'"));
  assert.ok(!d["connect-src"].includes("ws:"));
  assert.deepEqual(d["default-src"], ["'self'"]);
});

test("development policy allows what React Refresh needs", () => {
  const d = directives(buildCsp({ dev: true }));
  assert.ok(d["script-src"].includes("'unsafe-eval'"));
  assert.ok(d["connect-src"].includes("ws:"));
  assert.ok(d["connect-src"].includes("http://localhost:8000"));
});

test("framing, plugins, base and form targets are locked down in every mode", () => {
  for (const dev of [true, false]) {
    const d = directives(buildCsp({ dev, apiBase: "" }));
    assert.deepEqual(d["frame-ancestors"], ["'none'"]);
    assert.deepEqual(d["object-src"], ["'none'"]);
    assert.deepEqual(d["base-uri"], ["'self'"]);
    assert.deepEqual(d["form-action"], ["'self'"]);
  }
});

test("an explicit empty API base (Docker, same origin) adds no other origin", () => {
  const csp = buildCsp({ dev: false, apiBase: "" });
  assert.ok(!csp.includes("http://"), csp);
  // The only other origins are the speech-model hosts, and only for fetching data.
  const d = directives(csp);
  for (const [name, values] of Object.entries(d)) {
    const external = values.filter((v) => v.startsWith("https://"));
    if (name === "connect-src") assert.deepEqual(external, MODEL_HOSTS);
    else assert.deepEqual(external, [], name);
  }
});

test("in-browser engines may compile WebAssembly but scripts still come only from this site", () => {
  const d = directives(buildCsp({ dev: false, apiBase: "" }));
  assert.ok(d["script-src"].includes("'wasm-unsafe-eval'"));
  assert.ok(!d["script-src"].includes("'unsafe-eval'"));
  assert.ok(!d["script-src"].some((v) => v.startsWith("https:") || v === "*"));
  assert.deepEqual(d["worker-src"], ["'self'", "blob:"]);
  assert.deepEqual(MODEL_HOSTS, ["https://huggingface.co", "https://*.huggingface.co", "https://*.hf.co"]);
});

test("a separate API origin is allowed only for data, media and frames, as an origin", () => {
  const d = directives(buildCsp({ dev: false, apiBase: "https://api.example.org/base/path" }));
  for (const k of ["connect-src", "img-src", "media-src", "frame-src"]) {
    assert.ok(d[k].includes("https://api.example.org"), k);
  }
  assert.ok(!d["script-src"].includes("https://api.example.org"));
  assert.ok(!d["default-src"].includes("https://api.example.org"));
  assert.ok(!buildCsp({ dev: false, apiBase: "https://api.example.org/base/path" }).includes("/base/path"));
});

test("an unset API base in production allows only the loopback fallback of the client", () => {
  const d = directives(buildCsp({ dev: false, apiBase: undefined }));
  assert.ok(d["connect-src"].includes("http://localhost:8000"));
  assert.ok(d["connect-src"].includes("http://127.0.0.1:8000"));
  assert.ok(!d["script-src"].includes("http://localhost:8000"));
});

test("an invalid API base is ignored rather than injected into the policy", () => {
  const csp = buildCsp({ dev: false, apiBase: "not a url; script-src *" });
  assert.ok(!csp.includes("script-src *"));
  assert.ok(!csp.includes("not a url"));
});

test("every page gets the CSP plus the standard security headers", () => {
  const h = Object.fromEntries(securityHeaders({ dev: false, apiBase: "" }).map((x) => [x.key, x.value]));
  assert.equal(h["X-Content-Type-Options"], "nosniff");
  assert.equal(h["X-Frame-Options"], "DENY");
  assert.equal(h["Referrer-Policy"], "no-referrer");
  assert.match(h["Permissions-Policy"], /camera=\(\)/);
  assert.equal(h["Content-Security-Policy"], buildCsp({ dev: false, apiBase: "" }));
});

test("next.config applies the headers to every route and hides the X-Powered-By header", () => {
  const cfg = readFileSync(join(ROOT, "next.config.mjs"), "utf8");
  assert.match(cfg, /source:\s*"\/:path\*"/);
  assert.match(cfg, /securityHeaders\(/);
  assert.match(cfg, /poweredByHeader:\s*false/);
  // The production image must ship the module next.config imports at start-up.
  assert.match(readFileSync(join(ROOT, "Dockerfile"), "utf8"), /lib\/csp\.mjs/);
});
