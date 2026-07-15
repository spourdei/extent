import type { NextConfig } from "next";
import { fileURLToPath } from "node:url";

import { resolveApiOrigin } from "./src/server/api-origin.ts";

const scriptPolicy =
  process.env.NODE_ENV === "development"
    ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
    : "script-src 'self' 'unsafe-inline'";

const contentSecurityPolicy = [
  "default-src 'self'",
  scriptPolicy,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const repositoryRoot = fileURLToPath(new URL("../..", import.meta.url));
const backendOrigin = resolveApiOrigin(
  process.env.EXTENT_API_PROXY_TARGET,
  process.env.VERCEL_ENV,
);

const nextConfig: NextConfig = {
  distDir: process.env.EXTENT_NEXT_DIST_DIR ?? ".next",
  headers: () =>
    Promise.resolve([
      {
        headers: [
          { key: "Content-Security-Policy", value: contentSecurityPolicy },
          { key: "Permissions-Policy", value: "camera=(), geolocation=(), microphone=()" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
        source: "/(.*)",
      },
    ]),
  outputFileTracingRoot: repositoryRoot,
  poweredByHeader: false,
  reactStrictMode: true,
  rewrites: () =>
    Promise.resolve([
      {
        destination: `${backendOrigin}/api/:path*`,
        source: "/api/backend/:path*",
      },
    ]),
};

export default nextConfig;
