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
    if (!request.url.includes("/auth/")) pending.set(request, request.clone());
  },
  async onResponse({ request, response }) {
    const retry = pending.get(request);
    pending.delete(request);
    if (response.status !== 401 || !retry) return;
    if (await refreshOnce()) return fetch(retry);
  },
};

api.use(autoRefresh);

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
