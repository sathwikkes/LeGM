import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output is for the Docker image. Vercel packages the app itself and
  // fails its onBuildComplete step when standalone is on, so skip it there.
  output: process.env.VERCEL ? undefined : "standalone",
};

export default nextConfig;
