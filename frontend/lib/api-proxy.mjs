// Same-origin API proxy for deployments where the FastAPI backend runs as a separate
// project (for example two Vercel projects). Used by next.config.mjs, unit-tested.
//
// EVIDENCEX_API_ORIGIN is read on the SERVER at build time and never exposed to the
// browser. The browser calls /api/* and /health on this site; Next.js forwards them to
// the backend. Responses (including Set-Cookie) come back through this origin, so the
// HttpOnly, SameSite=Lax session cookie belongs to the site the user is on.

/**
 * The backend origin, validated: an absolute http(s) URL reduced to its origin.
 * Returns "" when unset. Throws for a malformed value so a misconfigured deployment
 * fails at build time instead of silently calling the wrong place.
 * @param {string | undefined} value
 */
export function proxyOrigin(value) {
  const text = (value ?? "").trim();
  if (!text) return "";
  let url;
  try {
    url = new URL(text);
  } catch {
    throw new Error("EVIDENCEX_API_ORIGIN must be an absolute URL such as https://api.example.com");
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new Error("EVIDENCEX_API_ORIGIN must use https:// (or http:// for local testing)");
  }
  if (url.pathname !== "/" || url.search || url.hash) {
    throw new Error("EVIDENCEX_API_ORIGIN must be an origin only, without a path");
  }
  return url.origin;
}

/**
 * Next.js rewrites that forward the API paths to the backend origin.
 * @param {string} origin
 */
export function apiProxyRewrites(origin) {
  if (!origin) return [];
  return [
    { source: "/api/:path*", destination: `${origin}/api/:path*` },
    { source: "/health", destination: `${origin}/health` },
  ];
}
