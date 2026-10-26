// Thông tin sân dùng cho SEO (metadata, JSON-LD) và giao diện.
// TODO: thay bằng thông tin thật của sân.
export const site = {
  name: "Sân Cầu Lông ABC",
  shortName: "Cầu Lông ABC",
  description:
    "Sân cầu lông ABC – sân thảm tiêu chuẩn, giá minh bạch theo khung giờ. Có chỗ gửi xe, nước uống, cho thuê vợt. Đặt sân tại quầy hoặc gọi hotline.",
  url: process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000",
  phone: "0900 000 000",
  email: "lienhe@example.com",
  address: {
    street: "123 Đường ABC",
    ward: "Phường XYZ",
    district: "Quận Cầu Giấy",
    city: "Hà Nội",
    country: "VN",
  },
  geo: { lat: 21.0333, lng: 105.8 },
  openingHours: { open: "05:00", close: "23:00" },
  social: {
    facebook: "https://facebook.com/",
    zalo: "https://zalo.me/",
  },
} as const;

/** Số điện thoại dạng gọi được (`tel:`). */
export const phoneHref = `tel:${site.phone.replace(/\s+/g, "")}`;

export const fullAddress = [
  site.address.street,
  site.address.ward,
  site.address.district,
  site.address.city,
].join(", ");
