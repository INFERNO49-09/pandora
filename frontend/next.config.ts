import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Allow server components to fetch from local API in dev
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: "http://localhost:8000/api/v1/:path*",
      },
    ];
  },
};

export default nextConfig;
