import { securityHeaders } from "./lib/csp.mjs";
import { apiProxyRewrites, proxyOrigin } from "./lib/api-proxy.mjs";

const dev = process.env.NODE_ENV !== "production";
// Server-side only (never sent to the browser): where the FastAPI backend is deployed.
// When set, the browser talks to this site only (same origin) and Next.js forwards
// /api/* and /health to the backend, so the session cookie stays first-party.
const apiOrigin = proxyOrigin(process.env.EVIDENCEX_API_ORIGIN);

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async rewrites() {
    return apiProxyRewrites(apiOrigin);
  },
  async headers() {
    return [
      {
        source: "/:path*",
        // Behind the proxy the API is same-origin: the CSP allows no other origin.
        headers: securityHeaders({
          dev,
          apiBase: apiOrigin ? "" : process.env.NEXT_PUBLIC_API_BASE_URL,
        }),
      },
    ];
  },
};

export default nextConfig;
