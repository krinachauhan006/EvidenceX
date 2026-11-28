// Content Security Policy for the web app (used by next.config.mjs and unit-tested).
//
// Next.js 14 (App Router, no nonce middleware) injects small inline scripts for
// hydration, so script-src needs 'unsafe-inline'; everything else is locked to the
// same origin. 'unsafe-eval' is added ONLY in development (React Refresh needs it).
// connect-src adds the API origin when the API is on a different origin (local
// development, or NEXT_PUBLIC_API_BASE_URL); in the recommended production setup the
// API is same-origin and nothing is added.

// Where Transformers.js fetches model files: the Hub, which redirects the large files
// to its content-delivery hosts (*.hf.co). Data only (connect-src), never scripts.
export const MODEL_HOSTS = ["https://huggingface.co", "https://*.huggingface.co", "https://*.hf.co"];

/** @param {{ dev: boolean, apiBase?: string }} opts */
export function buildCsp({ dev, apiBase }) {
  // A separate API origin (local development, or an explicit NEXT_PUBLIC_API_BASE_URL)
  // serves JSON, evidence downloads and media streams, so it is allowed for those only.
  const api = [];
  if (apiBase) {
    try {
      api.push(new URL(apiBase).origin);
    } catch {
      /* invalid URL: ignore, same-origin only */
    }
  }
  // NEXT_PUBLIC_API_BASE_URL not set at all: on a loopback host the client falls back
  // to port 8000 on that host (lib/api/client.ts), so allow exactly those origins.
  // An explicit empty value (the Docker image) means same-origin only.
  if (dev || apiBase === undefined) api.push("http://localhost:8000", "http://127.0.0.1:8000");
  const directives = {
    "default-src": ["'self'"],
    // 'wasm-unsafe-eval' lets the in-browser OCR and speech engines compile their
    // WebAssembly (served from this site, /engines). It does NOT allow eval() of
    // JavaScript; 'unsafe-eval' stays development-only.
    "script-src": [
      "'self'",
      "'unsafe-inline'",
      "'wasm-unsafe-eval'",
      ...(dev ? ["'unsafe-eval'"] : []),
    ],
    "style-src": ["'self'", "'unsafe-inline'"],
    "img-src": ["'self'", "data:", "blob:", ...api],
    "media-src": ["'self'", "blob:", ...api],
    "font-src": ["'self'", "data:"],
    // MODEL_HOSTS: the browser downloads the speech model's weights from the Hugging
    // Face Hub (fetch only; never scripts, and evidence is never sent there).
    "connect-src": ["'self'", ...api, ...MODEL_HOSTS, ...(dev ? ["ws:"] : [])],
    // Report previews are PDFs shown from blob: URLs in an iframe.
    "frame-src": ["'self'", "blob:", ...api],
    "worker-src": ["'self'", "blob:"],
    "object-src": ["'none'"],
    "base-uri": ["'self'"],
    "form-action": ["'self'"],
    "frame-ancestors": ["'none'"],
  };
  return Object.entries(directives)
    .map(([k, v]) => `${k} ${[...new Set(v)].join(" ")}`)
    .join("; ");
}

/** Security headers for every page. */
export function securityHeaders({ dev, apiBase }) {
  return [
    { key: "Content-Security-Policy", value: buildCsp({ dev, apiBase }) },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "X-Frame-Options", value: "DENY" },
    { key: "Referrer-Policy", value: "no-referrer" },
    { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  ];
}
