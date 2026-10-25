import type { NextConfig } from "next";
import { securityHeaders } from "./src/lib/securityHeaders.ts";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  // #449 PL-23: CSP and related headers on every route (src/lib/securityHeaders.ts, tested there).
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders(process.env, process.env.NODE_ENV !== "production") }];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
