import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/v1/admin/:path*", destination: `${process.env.ADMIN_API_ORIGIN ?? "http://127.0.0.1:8000"}/api/v1/admin/:path*` }];
  },
};

export default nextConfig;
