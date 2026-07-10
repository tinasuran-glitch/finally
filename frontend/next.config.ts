import type { NextConfig } from "next";

// Production is a static export served same-origin by FastAPI, so `/api/*`
// resolves directly. In `next dev` the frontend and backend are on different
// ports, so we proxy `/api/*` to the backend (no CORS needed). Static export
// doesn't support rewrites, hence the dev-only split.
const isDev = process.env.NODE_ENV === "development";
const BACKEND_ORIGIN =
  process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = isDev
  ? {
      // This machine's localhost resolves to a colliding Docker container, so
      // local testing uses 127.0.0.1. Next blocks cross-origin dev resources
      // (breaking hydration/HMR) unless the host is allowlisted here.
      allowedDevOrigins: ["127.0.0.1"],
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
