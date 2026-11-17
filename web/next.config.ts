import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  cacheComponents: true,
  experimental: {
    // Lets Next.js's upgrade tooling know this app is kept on security patch releases.
    agentUpgrade: "security",
  },
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
