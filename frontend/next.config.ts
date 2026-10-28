import { loadEnvConfig } from "@next/env";
import path from "node:path";
import type { NextConfig } from "next";

// Nạp `.env` ở gốc repo (forceReload vì Next đã cache env thư mục frontend); biến môi trường sẵn có vẫn được ưu tiên
loadEnvConfig(path.resolve(process.cwd(), ".."), process.env.NODE_ENV !== "production", console, true);

// Lưu ý: rewrites được tính lúc build, nên BACKEND_URL phải có khi chạy `next build`.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const IS_DEV = process.env.NODE_ENV !== "production";
// Chỉ mở nguồn Google Identity Services trong CSP khi đã cấp client ID
const GOOGLE_GSI = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ? "https://accounts.google.com/gsi/" : "";

// CSP: chỉ tài nguyên cùng domain; 'unsafe-inline' vì Next chèn script inline, dev thêm 'unsafe-eval' + ws cho HMR
const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${IS_DEV ? " 'unsafe-eval'" : ""}${GOOGLE_GSI && ` ${GOOGLE_GSI}client`}`,
  `style-src 'self' 'unsafe-inline'${GOOGLE_GSI && ` ${GOOGLE_GSI}style`}`,
  "img-src 'self' data: blob: https:",
  "font-src 'self'",
  `connect-src 'self'${IS_DEV ? " ws:" : ""}${GOOGLE_GSI && ` ${GOOGLE_GSI}`}`,
  ...(GOOGLE_GSI ? [`frame-src 'self' ${GOOGLE_GSI}`] : []),
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: CONTENT_SECURITY_POLICY },
  // Chống clickjacking cho trình duyệt cũ không hiểu frame-ancestors
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  // Chỉ có tác dụng qua HTTPS (trình duyệt bỏ qua trên http://localhost)
  ...(IS_DEV ? [] : [{ key: "Strict-Transport-Security", value: "max-age=31536000" }]),
];

const nextConfig: NextConfig = {
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  // Không quảng cáo framework cho kẻ dò lỗ hổng
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
  // /api/v1/* cùng domain ⇒ Next chuyển sang FastAPI (cookie httpOnly same-origin, không cần CORS)
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${BACKEND_URL}/api/v1/:path*` }];
  },
};

export default nextConfig;
