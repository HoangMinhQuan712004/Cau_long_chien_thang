import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { cookies } from "next/headers";
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Court = components["schemas"]["CourtOut"];
export type PriceRule = components["schemas"]["PriceRuleOut"];
export type PostSummary = components["schemas"]["PostSummary"];
export type Post = components["schemas"]["PostOut"];
export type Booking = components["schemas"]["BookingOut"];
export type User = components["schemas"]["UserOut"];

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
