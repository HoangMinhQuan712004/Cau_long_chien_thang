import type { NextConfig } from "next";

// Lưu ý: rewrites được tính lúc build, nên BACKEND_URL phải có khi chạy `next build`.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  // Trình duyệt gọi /api/v1/* cùng domain -> Next chuyển tiếp sang FastAPI.
  // Cookie httpOnly vì vậy là same-origin, không cần CORS.
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${BACKEND_URL}/api/v1/:path*` }];
  },
};

export default nextConfig;
