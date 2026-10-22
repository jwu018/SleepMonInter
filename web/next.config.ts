import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  cacheComponents: true,
  // The data module reads web/data/ with fs at runtime. Next can't always see which files
  // that needs, so list them explicitly or they'd be missing from the Vercel deployment.
  outputFileTracingIncludes: {
    "/**": ["./data/**/*"],
  },
  partialPrefetching: true,
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
