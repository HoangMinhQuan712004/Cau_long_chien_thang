import "client-only";
import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";

// Gọi API từ trình duyệt qua đường dẫn tương đối /api/v1/... (Next rewrite sang backend),
// nên cookie httpOnly là same-origin, không cần cấu hình CORS.
export const api = createClient<paths>({ baseUrl: "", credentials: "include" });

// Access token sống ngắn: khi gặp 401 thì gọi /auth/refresh một lần rồi thử lại request.
const pending = new WeakMap<Request, Request>();
let refreshing: Promise<boolean> | null = null;

const refreshOnce = () =>
  (refreshing ??= fetch("/api/v1/auth/refresh", { method: "POST", credentials: "include" })
    .then((r) => r.ok)
    .finally(() => {
      refreshing = null;
    }));

const autoRefresh: Middleware = {
  onRequest({ request }) {
    // /auth/* (đăng nhập, refresh…) không thử lại; riêng /auth/phone/* cần phiên khách như API thường.
    // Khu /admin dùng phiên server (cookie admin_session), không có refresh token.
    const url = request.url;
    if (!url.includes("/admin") && (!url.includes("/auth/") || url.includes("/auth/phone/"))) pending.set(request, request.clone());
  },
  async onResponse({ request, response }) {
    const retry = pending.get(request);
    pending.delete(request);
    if (response.status !== 401 || !retry) return;
    if (await refreshOnce()) return fetch(retry);
  },
};

api.use(autoRefresh);

// Phiên Admin/nhân viên (server-side, 12 giờ) hết hạn / bị thu hồi khi đang ở khu /admin ⇒ về màn đăng nhập kèm lý do (T-013 AC5).
const ADMIN_REASON: Record<string, string> = { expired: "het-han", password_changed: "doi-mat-khau", account_disabled: "tai-khoan-khoa" };
let leaving = false;
const adminSessionEnded: Middleware = {
  async onResponse({ response }) {
    if (leaving || response.status !== 401 || !window.location.pathname.startsWith("/admin")) return;
    const detail = errorDetail(await response
      .clone()
      .json()
      .catch(() => null));
    if (detail.code !== "E-AUTH-1") return;
    leaving = true;
    const reason = detail.reason && ADMIN_REASON[detail.reason];
    window.location.replace(`/dang-nhap?next=${encodeURIComponent(window.location.pathname)}${reason ? `&ly-do=${reason}` : ""}`);
  },
};
api.use(adminSessionEnded);

// Khách còn mật khẩu ban đầu (= SĐT): 403 E-AUTH-25 ⇒ trang đổi mật khẩu; E-AUTH-30 (quá hạn) ⇒ Quên mật khẩu (T-015)
export const MUST_CHANGE_PASSWORD_PATH = "/doi-mat-khau";
const mustChangePassword: Middleware = {
  async onResponse({ response }) {
    if (leaving || response.status !== 403 || window.location.pathname === MUST_CHANGE_PASSWORD_PATH) return;
    const detail = errorDetail(await response
      .clone()
      .json()
      .catch(() => null));
    // E-AUTH-30: mật khẩu ban đầu hết hạn ⇒ chỉ còn cách Quên mật khẩu (OTP)
    const target = detail.code === "E-AUTH-25" ? MUST_CHANGE_PASSWORD_PATH : detail.code === "E-AUTH-30" ? "/quen-mat-khau" : null;
    if (!target) return;
    leaving = true;
    window.location.replace(target);
  },
};
api.use(mustChangePassword);

// Client không ràng kiểu cho các endpoint chưa có trong schema.d.ts (booking engine T-006 cho tới khi BACKEND handoff).
// TODO(T-006): sau khi `npm run gen:api` có đủ đường dẫn, chuyển các lời gọi sang `api` và xóa `looseApi`.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const looseApi = createClient<any>({ baseUrl: "", credentials: "include" });
looseApi.use(autoRefresh);
looseApi.use(adminSessionEnded);
looseApi.use(mustChangePassword);

/** Lấy thông báo lỗi tiếng Việt từ response lỗi của FastAPI (hỗ trợ `detail` chuỗi, mảng và `{code, message}`). */
export function errorMessage(error: unknown, fallback = "Có lỗi xảy ra, vui lòng thử lại"): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);
  if (detail && typeof detail === "object" && "message" in detail) {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string" && message) return message;
  }
  return fallback;
}

/** Đọc `detail: { code, retry_after?, attempts_left?, reason? }` của lỗi nghiệp vụ; lỗi khác ⇒ `{}`. */
export function errorDetail(error: unknown): {
  code?: string;
  retry_after?: number;
  attempts_left?: number;
  reason?: string;
} {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  return detail && typeof detail === "object" && !Array.isArray(detail) ? detail : {};
}
