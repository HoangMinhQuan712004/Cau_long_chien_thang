import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { cookies } from "next/headers";
import { cache } from "react";
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

// OpenAPI sinh `bands` dạng tuple [string, string][] nhưng response thật được kiểu hóa là string[][] – khai báo lại cho khớp.
export type PublicPrices = Omit<components["schemas"]["PublicPrices"], "peak_bands"> & {
  peak_bands: { resource_type_code: string; bands: string[][] }[];
};
export type PostSummary = components["schemas"]["PostSummary"];
export type Post = components["schemas"]["PostOut"];
export type User = components["schemas"]["UserOut"];
export type Staff = components["schemas"]["StaffOut"];
export type StaffSession = components["schemas"]["StaffSessionOut"];
export type AdminSession = components["schemas"]["AdminSessionOut"];
/** Lý do phiên Admin/nhân viên không dùng được (backend: E-AUTH-1 + detail.reason). */
export type AdminSessionError = "unauthenticated" | "expired" | "password_changed" | "account_disabled";

export const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const serverApi = createClient<paths>({ baseUrl: BACKEND_URL });

/** Gọi API public; lỗi mạng (vd: lúc build không có backend) trả về fallback thay vì làm hỏng trang. */
async function safe<T>(fn: () => Promise<{ data?: T }>, fallback: T): Promise<T> {
  try {
    return (await fn()).data ?? fallback;
  } catch (e) {
    console.error("[api]", e);
    return fallback;
  }
}

// ---------- Dữ liệu public: cache phía server, prerender vào static shell (tốt cho SEO) ----------

/** Bảng giá công khai (bản rút gọn từ booking engine: giá, giờ cao điểm, giờ mở cửa, ngày Lễ/Tết). */
export async function getPublicPrices(): Promise<PublicPrices | null> {
  "use cache";
  cacheLife("minutes");
  cacheTag("prices");
  // Không đổi cacheLife theo kết quả: profile quá ngắn khiến Next coi là dữ liệu động → prerender lỗi khi build không có backend (CI, Docker).
  // Lỗi mạng chỉ làm trang rơi về "đang cập nhật" tới lần revalidate kế tiếp (≤ 1 phút).
  return safe(() => serverApi.GET("/api/v1/booking/prices/public"), null);
}

export async function getPosts(limit = 20): Promise<PostSummary[]> {
  "use cache";
  cacheLife("minutes");
  cacheTag("posts");
  return safe(() => serverApi.GET("/api/v1/posts", { params: { query: { limit } } }), []);
}

export async function getPost(slug: string): Promise<Post | null> {
  "use cache";
  cacheLife("minutes");
  cacheTag("posts", `post:${slug}`);
  return safe(() => serverApi.GET("/api/v1/posts/{slug}", { params: { path: { slug } } }), null);
}

// ---------- Dữ liệu theo người dùng: đọc cookie, KHÔNG cache, phải nằm sau <Suspense> ----------

/** Client API gắn cookie của request hiện tại (để backend xác thực). */
export async function authedApi() {
  const cookieHeader = (await cookies()).toString();
  return createClient<paths>({ baseUrl: BACKEND_URL, headers: { cookie: cookieHeader } });
}

export async function getCurrentUser(): Promise<User | null> {
  const api = await authedApi();
  const { data } = await api.GET("/api/v1/auth/me");
  return data ?? null;
}

/** Phiên Admin/nhân viên (cookie `admin_session`); lỗi ⇒ lý do để màn đăng nhập giải thích. Một lần mỗi request. */
export const getAdminSession = cache(
  async (): Promise<{ ok: true; session: AdminSession } | { ok: false; reason: AdminSessionError }> => {
    const api = await authedApi();
    const { data, error } = await api.GET("/api/v1/admin/auth/me");
    if (data) return { ok: true, session: data };
    const reason = (error as { detail?: { reason?: string } } | undefined)?.detail?.reason;
    const known: AdminSessionError[] = ["expired", "password_changed", "account_disabled"];
    return { ok: false, reason: known.find((c) => c === reason) ?? "unauthenticated" };
  },
);

/**
 * GET JSON kèm cookie người dùng cho endpoint chưa có trong schema.d.ts (booking engine T-006).
 * TODO(T-006): chuyển sang `authedApi()` khi `schema.d.ts` có đủ đường dẫn.
 */
export async function authedGetJson<T>(
  path: string,
  query: Record<string, string | undefined> = {},
): Promise<{ ok: true; data: T } | { ok: false; status: number }> {
  const cookieHeader = (await cookies()).toString();
  const qs = new URLSearchParams(Object.entries(query).filter((e): e is [string, string] => e[1] !== undefined)).toString();
  try {
    const res = await fetch(`${BACKEND_URL}${path}${qs ? `?${qs}` : ""}`, { headers: { cookie: cookieHeader }, cache: "no-store" });
    if (!res.ok) return { ok: false, status: res.status };
    return { ok: true, data: (await res.json()) as T };
  } catch {
    return { ok: false, status: 0 };
  }
}
