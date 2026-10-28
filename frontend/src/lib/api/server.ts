import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { cookies } from "next/headers";
import { cache } from "react";
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

type Court = components["schemas"]["CourtOut"];
export type PriceRule = components["schemas"]["PriceRuleOut"];
type PostSummary = components["schemas"]["PostSummary"];
type Post = components["schemas"]["PostOut"];
type User = components["schemas"]["UserOut"];
type AdminSession = components["schemas"]["AdminSessionOut"];
export type Staff = components["schemas"]["StaffOut"];
export type StaffSession = components["schemas"]["StaffSessionOut"];

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

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

export async function getCourts(): Promise<Court[]> {
  "use cache";
  cacheLife("minutes");
  cacheTag("courts");
  return safe(() => serverApi.GET("/api/v1/courts"), []);
}

export async function getPriceRules(): Promise<PriceRule[]> {
  "use cache";
  cacheLife("minutes");
  cacheTag("price-rules");
  return safe(() => serverApi.GET("/api/v1/price-rules"), []);
}

export async function getVenueConfig() {
  "use cache";
  cacheLife("hours");
  return safe(() => serverApi.GET("/api/v1/venue/config"), null);
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

/** Lý do không vào được khu quản trị (backend `/admin/auth/me` trả 401 kèm `code`). */
export type AdminSessionError = "unauthenticated" | "expired" | "password_changed" | "account_disabled";

/** Một lần mỗi request dù layout, menu và trang cùng gọi. */
export const getAdminSession = cache(async (): Promise<
  { ok: true; session: AdminSession } | { ok: false; reason: AdminSessionError }
> => {
  const api = await authedApi();
  const { data, error } = await api.GET("/api/v1/admin/auth/me");
  if (data) return { ok: true, session: data };
  const code = (error as { detail?: { code?: string } } | undefined)?.detail?.code;
  const known: AdminSessionError[] = ["expired", "password_changed", "account_disabled"];
  return { ok: false, reason: known.find((c) => c === code) ?? "unauthenticated" };
});
