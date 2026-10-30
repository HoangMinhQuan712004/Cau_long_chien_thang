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
export function destination(kind: "admin" | "member", next: string): string {
  // Đúng khu /admin (không nhận nhầm "/administrator", "/admin-x")
  const isAdminPath = /^\/admin(?:[/?#]|$)/.test(next);
  if (kind === "admin") return isAdminPath ? next : "/admin";
  return next && !isAdminPath ? next : "/";
}
