import "client-only";
import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";

// Client API phía trình duyệt, gọi /api/v1/* cùng domain (Next rewrite sang backend)
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
    // /auth/* (đăng nhập, refresh…) không thử lại; riêng /auth/phone/* cần phiên khách như API thường
    const url = request.url;
    if (!url.includes("/auth/") || url.includes("/auth/phone/")) pending.set(request, request.clone());
  },
  async onResponse({ request, response }) {
    const retry = pending.get(request);
    pending.delete(request);
    if (response.status !== 401 || !retry) return;
    if (await refreshOnce()) return fetch(retry);
  },
};

api.use(autoRefresh);

/** Lấy thông báo lỗi tiếng Việt từ response lỗi của FastAPI. */
export function errorMessage(error: unknown, fallback = "Có lỗi xảy ra, vui lòng thử lại"): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  // 422 Pydantic: bỏ tiền tố "Value error, "
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg).replace(/^Value error, /, "");
  return fallback;
}

/** Đọc `detail: { code, retry_after?, attempts_left? }` của lỗi nghiệp vụ; lỗi khác ⇒ `{}`. */
export function errorDetail(error: unknown): {
  code?: string;
  retry_after?: number;
  attempts_left?: number;
} {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  return detail && typeof detail === "object" && !Array.isArray(detail) ? detail : {};
}
