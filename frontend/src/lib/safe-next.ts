const BASE = "http://internal.invalid";

/** Chỉ cho phép chuyển hướng nội bộ (chống open redirect qua ?next=). */
export function safeNext(next: string | null | undefined, fallback = "/tai-khoan"): string {
  // Ký tự điều khiển bị trình duyệt bỏ qua ("/\t/evil.com" -> "//evil.com") -> từ chối luôn
  if (!next || !next.startsWith("/") || /[\u0000-\u001F\u007F\\]/.test(next)) return fallback;
  try {
    const url = new URL(next, BASE);
    if (url.origin !== BASE) return fallback;
    return url.pathname + url.search + url.hash;
  } catch {
    return fallback;
  }
}

/** Đích sau đăng nhập theo quyền: Admin/nhân viên chỉ vào khu quản trị, khách (`member`) không vào khu quản trị. */
export function destination(kind: "admin" | "member", next: string, memberFallback = "/"): string {
  // Đúng khu /admin (không nhận nhầm "/administrator", "/admin-x")
  const isAdminPath = /^\/admin(?:[/?#]|$)/.test(next);
  if (kind === "admin") return isAdminPath ? next : "/admin";
  return next && !isAdminPath ? next : memberFallback;
}

/** Trang đặt sân công khai ("/" chuyển 308 tới "/dat-san"): hội viên không dùng, đi thẳng khu hội viên. */
export function isPublicBooking(path: string): boolean {
  return /^\/(?:dat-san\/?)?(?:[?#]|$)/.test(path);
}

/**
 * Đích của hội viên đã đăng nhập: trang đặt sân công khai ⇒ Tổng quan `/hoi-vien`; có ngày / booking (`date`, `ngay` cũ,
 * `event`) ⇒ `/hoi-vien/dat-san` cùng tham số. Đích khác (và rỗng ⇒ Tổng quan) giữ nguyên.
 */
export function memberHome(next: string): string {
  if (next && !isPublicBooking(next)) return next;
  const from = new URL(next || "/", BASE).searchParams;
  const query = new URLSearchParams();
  const date = from.get("date") ?? from.get("ngay");
  if (date) query.set("date", date);
  const event = from.get("event");
  if (event) query.set("event", event);
  return query.size ? `/hoi-vien/dat-san?${query}` : "/hoi-vien";
}
