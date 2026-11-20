import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The container runs `node server.js` from a minimal standalone bundle.
  output: "standalone",
};

export default nextConfig;
