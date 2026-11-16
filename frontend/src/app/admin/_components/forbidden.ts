import type { components } from "@/lib/api/schema";

// Quyền + chặn không đủ quyền của khu quản trị. Tách khỏi file "use client": server import hằng từ file client sẽ nhận tham chiếu, không phải giá trị

/** Tham số gắn khi chuyển về vì không đủ quyền (vd Nhân viên mở link Lịch sử thao tác). */
export const FORBIDDEN_KEY = "ly-do";
export const FORBIDDEN_VALUE = "khong-quyen";
export const FORBIDDEN_PARAM = `${FORBIDDEN_KEY}=${FORBIDDEN_VALUE}`;

/** Nhân viên mở link Báo cáo ⇒ câu riêng "Bạn không có quyền xem báo cáo." (E-001 Báo cáo & phân tích). */
export const FORBIDDEN_REPORT_VALUE = "khong-quyen-bao-cao";
export const FORBIDDEN_REPORT_PARAM = `${FORBIDDEN_KEY}=${FORBIDDEN_REPORT_VALUE}`;

/** Mã quyền trong `perms` của phiên (cùng enum Perm ở backend/app/core/permissions.py). */
export type AdminPerm =
  | "reports.view"
  | "booking.calendar.view"
  | "booking.orders.view"
  | "booking.recurring"
  | "play_rooms.monitor"
  | "booking.transactions.view"
  | "booking.config.manage"
  | "booking.resources.delete"
  | "member.manage"
  | "payments.settings"
  | "staff.manage"
  | "records.video.manage"
  | "audit_log.view"
  | "roles.manage"
  | "settings.menu"
  | "settings.site";

export const can = (perms: readonly string[], perm: AdminPerm) => perms.includes(perm);

/** Khóa mục menu trái (cùng enum MenuKey ở backend; thứ tự chung do Admin sắp ở Tùy chỉnh menu). */
export type MenuKey = components["schemas"]["MenuOrderIn"]["order"][number];

/** Mục menu quản trị theo thứ tự MẶC ĐỊNH + quyền cần có (khớp require() của API từng trang). */
export const ADMIN_NAV = [
  { href: "/admin/bao-cao", key: "baoCao", perm: "reports.view" },
  { href: "/admin/san", key: "san", perm: "booking.config.manage" },
  { href: "/admin/dat-san", key: "datSan", perm: "booking.calendar.view" },
  { href: "/admin/don-dat-san", key: "donDatSan", perm: "booking.orders.view" },
  { href: "/admin/theo-doi-san", key: "theoDoiSan", perm: "play_rooms.monitor" },
  { href: "/admin/hoi-vien", key: "hoiVien", perm: "member.manage" },
  { href: "/admin/lich-su-giao-dich", key: "lichSu", perm: "booking.transactions.view" },
  { href: "/admin/ky-luc", key: "kyLuc", perm: "records.video.manage" },
  { href: "/admin/cai-dat/thanh-toan", key: "thanhToan", perm: "payments.settings" },
  { href: "/admin/nhan-vien", key: "nhanVien", perm: "staff.manage" },
] as const satisfies readonly { href: string; key: MenuKey; perm: AdminPerm }[];

// Backend thêm MenuKey mới mà ADMIN_NAV chưa có ⇒ lỗi kiểu ở đây
type MissingNavKey = Exclude<MenuKey, (typeof ADMIN_NAV)[number]["key"]>;
const NAV_COVERS_ALL: MissingNavKey extends never ? true : MissingNavKey = true;
void NAV_COVERS_ALL;

export type NavItem = (typeof ADMIN_NAV)[number];
export const DEFAULT_MENU_ORDER: MenuKey[] = ADMIN_NAV.map((n) => n.key);

/** Sắp ADMIN_NAV theo thứ tự đã lưu; khóa thiếu / lạ thì nối theo thứ tự mặc định (an toàn khi thêm mục mới). */
export function sortNav(order: readonly string[] = []): NavItem[] {
  const rank = new Map(order.map((k, i) => [k, i]));
  return [...ADMIN_NAV].sort((a, b) => (rank.get(a.key) ?? 99 + DEFAULT_MENU_ORDER.indexOf(a.key)) - (rank.get(b.key) ?? 99 + DEFAULT_MENU_ORDER.indexOf(b.key)));
}

/** Trang đầu tiên (theo thứ tự menu) người này có quyền (vào /admin); không có mục nào ⇒ Hồ sơ của tôi. */
export const firstAllowedHref = (perms: readonly string[], order?: readonly string[]) =>
  sortNav(order).find((n) => can(perms, n.perm))?.href ?? "/admin/ho-so";
