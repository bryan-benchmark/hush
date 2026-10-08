import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Live SSE talks directly to the Python recorder on :8787 (CORS enabled).
};

export default nextConfig;
