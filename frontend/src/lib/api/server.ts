import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";
import { SITE_DEFAULTS } from "@/lib/site";
import createClient from "openapi-fetch";
import type { MemberMe } from "@/components/member-area/types";
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
export type StaffSessionHistory = components["schemas"]["StaffSessionHistoryOut"];
export type AdminSession = components["schemas"]["AdminSessionOut"];
export type SiteBranding = components["schemas"]["SiteBrandingOut"];
export type MemberList = components["schemas"]["MemberListOut"];
export type MemberRow = components["schemas"]["MemberRow"];
export type MemberCreated = components["schemas"]["MemberCreatedOut"];
export type MemberDetail = components["schemas"]["MemberDetail"];
export type Racket = components["schemas"]["RacketOut"];
export type AuditLogPage = components["schemas"]["AuditLogPageOut"];
export type AuditEntry = components["schemas"]["AuditEntryOut"];
export type AuditCatalog = components["schemas"]["AuditCatalogOut"];
export type AuditActorKind = AuditEntry["actor"];
export type ReportOverview = components["schemas"]["ReportOverviewOut"];
export type HeatColumn = components["schemas"]["HeatColumnOut"];
export type HeatCell = components["schemas"]["HeatCellOut"];
export type MemberTier = NonNullable<components["schemas"]["MemberRow"]["tier"]>;
/** Giá trị `tier` khi lọc danh sách (8 hạng + "chưa xếp hạng"). */
export type MemberTierFilter = NonNullable<NonNullable<paths["/api/v1/members"]["get"]["parameters"]["query"]>["tier"]>;
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

/** Logo + favicon công khai (null ⇒ biểu tượng mặc định). Đổi logo xong màn Logo web xóa tag này để trang khách thấy ngay. */
export async function getBranding(): Promise<SiteBranding> {
  "use cache";
  cacheLife("minutes");
  cacheTag("site-branding");
  // API lỗi ⇒ giá trị mặc định trong site.ts, không làm hỏng trang
  return safe(() => serverApi.GET("/api/v1/site/branding"), {
    ...SITE_DEFAULTS,
    map_url: null,
    lat: null,
    lng: null,
    logo_url: null,
    favicon_url: null,
  });
}

// ---------- Dữ liệu theo người dùng: đọc cookie, KHÔNG cache, phải nằm sau <Suspense> ----------

/** Client API gắn cookie của request hiện tại (để backend xác thực). */
export async function authedApi() {
  const cookieHeader = (await cookies()).toString();
  return createClient<paths>({ baseUrl: BACKEND_URL, headers: { cookie: cookieHeader } });
}

/** Phiên khách: `expired` = mật khẩu ban đầu (= SĐT) quá hạn (403 E-AUTH-30); lỗi mạng ⇒ coi như chưa đăng nhập. Một lần mỗi request. */
export const readCurrentUser = cache(async (): Promise<{ user: User | null; expired: boolean }> => {
  try {
    const api = await authedApi();
    const { data, error, response } = await api.GET("/api/v1/auth/me");
    const code = (error as { detail?: { code?: string } } | undefined)?.detail?.code;
    return { user: data ?? null, expired: response.status === 403 && code === "E-AUTH-30" };
  } catch {
    return { user: null, expired: false };
  }
});

/**
 * Khách đang đăng nhập (header, /tai-khoan, /doi-mat-khau). Mật khẩu ban đầu hết hạn ⇒ sang Quên mật khẩu
 * (BE không trả SĐT ⇒ không kèm `?sdt=`). Không ném lỗi ⇒ nơi gọi không cần `.catch` (sẽ nuốt mất redirect).
 */
export async function getCurrentUser(): Promise<User | null> {
  const { user, expired } = await readCurrentUser();
  if (expired) redirect("/quen-mat-khau");
  return user;
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

/** Quyền của phiên quản trị hiện tại (rỗng nếu hết phiên). Dùng để ẩn mục / chặn sớm; backend vẫn kiểm trên từng API. */
export async function adminPerms(): Promise<string[]> {
  const result = await getAdminSession().catch(() => null);
  return result?.ok ? result.session.perms : [];
}

/** Thứ tự menu trái chung (Admin sắp ở Tùy chỉnh menu); hết phiên ⇒ rỗng (dùng thứ tự mặc định). */
export async function adminMenuOrder(): Promise<string[]> {
  const result = await getAdminSession().catch(() => null);
  return result?.ok ? result.session.menu_order : [];
}

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

// ---------- Khu hội viên (T-016) ----------

/**
 * Hồ sơ hội viên của phiên hiện tại. 401 → chưa đăng nhập / hết phiên; 403: E-HV-8 chưa là hội viên,
 * E-AUTH-25 chưa đổi mật khẩu ban đầu. Một lần mỗi request.
 */
export const getMemberMe = cache(async (): Promise<{ ok: true; data: MemberMe } | { ok: false; status: number; code?: string }> => {
  const cookieHeader = (await cookies()).toString();
  try {
    const res = await fetch(`${BACKEND_URL}/api/v1/member-area/me`, { headers: { cookie: cookieHeader }, cache: "no-store" });
    if (res.ok) return { ok: true, data: (await res.json()) as MemberMe };
    const body = (await res.json().catch(() => null)) as { detail?: { code?: string } } | null;
    return { ok: false, status: res.status, code: body?.detail?.code };
  } catch {
    return { ok: false, status: 0 };
  }
});
