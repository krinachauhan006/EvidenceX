// Same-origin API proxy (lib/api-proxy.mjs, wired in next.config.mjs).
// Run: node --experimental-strip-types --no-warnings --test tests/api-proxy.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { apiProxyRewrites, proxyOrigin } from "../lib/api-proxy.mjs";
import { buildCsp } from "../lib/csp.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = (p) => readFileSync(join(ROOT, p), "utf8");

test("no backend origin configured: no rewrites (local development and Docker)", () => {
  assert.equal(proxyOrigin(undefined), "");
  assert.equal(proxyOrigin("   "), "");
  assert.deepEqual(apiProxyRewrites(""), []);
});

test("the backend origin is normalised to an origin", () => {
  assert.equal(proxyOrigin("https://evidencex-api.example.com"), "https://evidencex-api.example.com");
  assert.equal(proxyOrigin(" https://evidencex-api.example.com/ "), "https://evidencex-api.example.com");
});

test("malformed origins fail the build instead of proxying somewhere unexpected", () => {
  for (const bad of ["evidencex-api.example.com", "ftp://x.example.com", "https://x.example.com/api",
                     "https://x.example.com/?a=1", "javascript:alert(1)"]) {
    assert.throws(() => proxyOrigin(bad), /EVIDENCEX_API_ORIGIN/, bad);
  }
});

test("/api/* and /health are forwarded to the backend, nothing else", () => {
  const rules = apiProxyRewrites("https://evidencex-api.example.com");
  assert.deepEqual(rules, [
    { source: "/api/:path*", destination: "https://evidencex-api.example.com/api/:path*" },
    { source: "/health", destination: "https://evidencex-api.example.com/health" },
  ]);
});

test("next.config uses the proxy and a same-origin CSP when the backend origin is set", () => {
  const cfg = src("next.config.mjs");
  assert.match(cfg, /proxyOrigin\(process\.env\.EVIDENCEX_API_ORIGIN\)/);
  assert.match(cfg, /async rewrites\(\)\s*\{\s*return apiProxyRewrites\(apiOrigin\);/);
  assert.match(cfg, /apiBase: apiOrigin \? "" : process\.env\.NEXT_PUBLIC_API_BASE_URL/);
  // Same-origin policy: neither localhost nor the backend origin appears in the CSP.
  const csp = buildCsp({ dev: false, apiBase: "" });
  assert.ok(!csp.includes("localhost") && !csp.includes("http://") && !csp.includes("https://"), csp);
  // The backend origin stays server-side: it is not a NEXT_PUBLIC_ variable.
  assert.doesNotMatch(cfg, /NEXT_PUBLIC_EVIDENCEX_API_ORIGIN/);
});

test("the production Docker image ships the proxy module next.config imports", () => {
  assert.match(src("Dockerfile"), /COPY --from=build --chown=web:web \/app\/lib\/api-proxy\.mjs \.\/lib\/api-proxy\.mjs/);
});

test("the browser falls back to relative URLs on a deployed (non-loopback) host", () => {
  const client = src("lib/api/client.ts");
  assert.match(client, /return "";/); // defaultApiBase for any real host
  assert.match(client, /process\.env\.NEXT_PUBLIC_API_BASE_URL\?\.replace/);
});

test("uploads rejected by the platform as too large get a plain explanation", () => {
  const client = src("lib/api/client.ts");
  assert.match(client, /xhr\.status === 413/);
  assert.match(client, /UPLOAD_TOO_LARGE/);
});
