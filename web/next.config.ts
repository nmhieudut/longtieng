import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

// Built as a static site that FastAPI serves. In `next dev`, /api is proxied to FastAPI
// (rewrites are not allowed together with output: "export").
export default function config(phase: string): NextConfig {
  const base: NextConfig = {
    turbopack: {
      rules: {
        "*.css": { loaders: ["@tailwindcss/turbopack"], as: "*.css" },
      },
    },
  };
  if (phase === PHASE_DEVELOPMENT_SERVER) {
    return {
      ...base,
      async rewrites() {
        return [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" }];
      },
    };
  }
  return { ...base, output: "export", images: { unoptimized: true } };
}
