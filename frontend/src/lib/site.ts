// Tên, địa chỉ, hotline, email do Admin sửa ở Cài đặt > Thông tin web: trang đọc qua getBranding() (lib/api/server.ts).
// File này chỉ giữ phần không sửa được và giá trị dự phòng khi API lỗi.
export const site = {
  url: process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000",
} as const;

/** Dự phòng khi API lỗi (khớp mặc định của backend khi chưa lưu). */
export const SITE_DEFAULTS = {
  name: "Sân Cầu Lông ABC",
  address: "123 Đường ABC, Phường XYZ, Quận Cầu Giấy, Hà Nội",
  phone: "0900 000 000",
  email: "lienhe@example.com",
} as const;

/** Mô tả sân dùng cho SEO và trang chủ. */
export const siteDescription = (name: string) =>
  `${name} – sân thảm tiêu chuẩn, giá minh bạch theo khung giờ. Có chỗ gửi xe, nước uống, cho thuê vợt. Đặt sân online thanh toán bằng chuyển khoản QR, hoặc tại quầy / gọi hotline.`;

/** Số gọi được (`tel:`): bỏ mọi ký tự không phải số, giữ dấu + đầu. */
export const phoneHref = (phone: string) => `tel:${phone.trim().startsWith("+") ? "+" : ""}${phone.replace(/\D/g, "")}`;

/** Tên khu quản trị theo tên sân: "Quản trị {name}" ⇒ "QUẢN TRỊ SÂN CẦU LÔNG ABC". */
export const adminBrand = (template: string, name: string) => template.replace("{name}", name).toLocaleUpperCase("vi");
