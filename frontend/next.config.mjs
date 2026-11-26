import { securityHeaders } from "./lib/csp.mjs";

const dev = process.env.NODE_ENV !== "production";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders({ dev, apiBase: process.env.NEXT_PUBLIC_API_BASE_URL }),
      },
    ];
  },
};

export default nextConfig;
