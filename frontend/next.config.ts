import type { NextConfig } from "next";

// Server-side rewrites run inside the Next.js process itself, so this needs
// the address the *frontend container* can reach the backend at — not the
// browser-facing NEXT_PUBLIC_API_URL. In docker-compose that's the service
// name "api", not "localhost" (the frontend container's own loopback).
// Falls back to localhost:8000 for running `next dev` directly on the host.
const backendInternalUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  // Allow server components to fetch from the API in dev
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${backendInternalUrl}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
