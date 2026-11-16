import type { NextConfig } from "next";

// Lưu ý: rewrites được tính lúc build, nên BACKEND_URL phải có khi chạy `next build`.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const isDev = process.env.NODE_ENV === "development";
// Chỉ mở nguồn Google Identity Services trong CSP khi đã cấp client ID (T-013 AC37).
const GSI = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ? "https://accounts.google.com/gsi/" : "";

// Header bảo mật (ADR-004 S5 / T-005 B9). HSTS và Referrer-Policy do Caddy đặt.
// CSP KHÔNG dùng nonce: nonce buộc mọi trang render động, làm mất prerender + Partial Prerendering của trang public (SEO).
// Đã thử nonce riêng cho /admin/* (proxy.ts đặt CSP + x-nonce): với Cache Components, "static shell" của các trang admin
// (PPR) được dựng lúc build nên script trong shell không có nonce → trình duyệt chặn, trang không hydrate (kiểm 26/10).
// Vì vậy script/style cho phép 'unsafe-inline' (Next cần cho script khởi động và payload RSC); các lớp còn lại giữ chặt:
// frame-ancestors, object-src, base-uri, form-action, connect-src và nguồn ảnh. XSS được chặn ở tầng ứng dụng
// (React tự escape, không dùng dangerouslySetInnerHTML với dữ liệu người dùng).
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}${GSI && ` ${GSI}client`}`,
  `style-src 'self' 'unsafe-inline'${GSI && ` ${GSI}style`}`,
  "img-src 'self' data: blob: https://qr.sepay.vn https://i.ytimg.com",
  "font-src 'self' data:",
  `connect-src 'self'${GSI && ` ${GSI}`}`,
  // Video kỷ lục (T-046): YouTube chỉ nạp iframe khi bấm phát; file .mp4 / .webm do Admin dán link https. Google: bản đồ địa chỉ sân
  `frame-src 'self' https://www.youtube-nocookie.com https://www.google.com${GSI && ` ${GSI}`}`,
  "media-src 'self' https:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()" },
];

const nextConfig: NextConfig = {
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  async headers() {
    return [
      { source: "/(.*)", headers: securityHeaders },
      // Trang thanh toán chứa token lượt giữ chỗ: không cache, không index (T-008 AC29, SEC9).
      {
        source: "/thanh-toan/:path*",
        headers: [
          { key: "Cache-Control", value: "no-store" },
          { key: "X-Robots-Tag", value: "noindex, nofollow" },
        ],
      },
      // Khu hội viên: dữ liệu cá nhân, không cache, không index (T-016 AC6).
      {
        source: "/hoi-vien/:path*",
        headers: [
          { key: "Cache-Control", value: "no-store" },
          { key: "X-Robots-Tag", value: "noindex, nofollow" },
        ],
      },
    ];
  },
  // Người dùng 04/11: bỏ trang chủ giới thiệu, /dat-san là trang chính (mang JSON-LD + mô tả của trang chủ cũ).
  // Vĩnh viễn (308) để Google chuyển thứ hạng của "/" sang /dat-san. Trang app/(public)/page.tsx không còn ai vào được.
  async redirects() {
    return [{ source: "/", destination: "/dat-san", permanent: true }];
  },
  // Trình duyệt gọi /api/v1/* cùng domain -> Next chuyển tiếp sang FastAPI.
  // Cookie httpOnly vì vậy là same-origin, không cần CORS.
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${BACKEND_URL}/api/v1/:path*` }];
  },
};

export default nextConfig;
