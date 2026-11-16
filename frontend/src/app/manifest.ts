import type { MetadataRoute } from "next";
import { getBranding } from "@/lib/api/server";
import { APP_NAME } from "@/lib/site";

// Manifest cho app cài từ web (PWA): đủ điều kiện ⇒ Chrome / Edge hiện "Cài đặt ứng dụng" và cài thành app riêng
// (Android: có trong ngăn ứng dụng, mở toàn màn hình không thanh địa chỉ / thanh tiêu đề). Tên app cố định
// APP_NAME; mô tả theo tên web ở Cài đặt › Thông tin web.
// Không cần service worker để cài được (không cache dữ liệu đăng nhập).

// Manifest chỉ nhận mã màu: xanh header ≈ --appbar (người dùng 13/11, trùng themeColor ở app/layout.tsx). Android tô cả thanh
// trạng thái lẫn thanh điều hướng bằng một màu này (không tách được bằng web) ⇒ màn chờ mở app cũng cùng màu
const THEME = "#234839";

export default async function manifest(): Promise<MetadataRoute.Manifest> {
  const { name } = await getBranding();
  return {
    id: "/",
    name: APP_NAME,
    short_name: APP_NAME,
    description: `Đặt sân, phòng chơi, bảng xếp hạng – ${name}`,
    lang: "vi",
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: THEME,
    theme_color: THEME,
    icons: [
      { src: "/pwa-icon/192", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/pwa-icon/512", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/pwa-icon/192-maskable", sizes: "192x192", type: "image/png", purpose: "maskable" },
      { src: "/pwa-icon/512-maskable", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
