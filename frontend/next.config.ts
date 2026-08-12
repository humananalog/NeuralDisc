import type { NextConfig } from "next";

const API_URL = process.env.NEURALDISC_API_URL || "http://127.0.0.1:8020";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_URL}/api/:path*`,
      },
    ];
  },
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
