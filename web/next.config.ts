import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  allowedDevOrigins: ["127.0.0.1"],
  experimental: { optimizePackageImports: ["lucide-react"] },
  async rewrites() {
    const api = process.env.HOPE_API_INTERNAL_URL ?? "http://localhost:8000";
    return [
      { source: "/api/:path*", destination: `${api}/api/:path*` },
      { source: "/health/:path*", destination: `${api}/health/:path*` },
    ];
  },
};

export default nextConfig;
