import type { NextConfig } from "next";

// Production is a static export served same-origin by FastAPI, so `/api/*`
// resolves directly. In `next dev` the frontend and backend are on different
// ports, so we proxy `/api/*` to the backend (no CORS needed). Static export
// doesn't support rewrites, hence the dev-only split.
const isDev = process.env.NODE_ENV === "development";
const BACKEND_ORIGIN =
  process.env.BACKEND_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = isDev
  ? {
      async rewrites() {
        return [
          { source: "/api/:path*", destination: `${BACKEND_ORIGIN}/api/:path*` },
        ];
      },
    }
  : {
      output: "export",
      images: { unoptimized: true },
    };

export default nextConfig;
