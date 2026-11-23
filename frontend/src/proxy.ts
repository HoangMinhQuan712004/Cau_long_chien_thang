import { type NextRequest, NextResponse } from "next/server";

// T-077: giữ phiên khách / hội viên khi `access_token` (sống 30 phút) hết hạn mà `refresh_token` còn hạn.
// Trước đây chỉ kiểm có cookie nên quá 30 phút là bị đẩy về /dang-nhap dù vẫn còn refresh token; refresh chỉ chạy ở trình duyệt khi gặp 401,
// mà lúc mở lại app trang được render ở server nên không bao giờ tới bước đó. Nay proxy làm mới TRƯỚC khi render:
//   · thiếu access_token, hoặc JWT còn < 2 phút, mà có refresh_token ⇒ POST /api/v1/auth/refresh tới backend nội bộ;
//   · thành công ⇒ chuyển Set-Cookie xuống trình duyệt và gán cookie mới vào request để RSC đọc được ngay;
//   · backend trả 401 (hết hạn / bị thu hồi / đổi mật khẩu / khóa) ⇒ xóa cookie; trang cần đăng nhập về /dang-nhap?next=…;
//   · lỗi mạng / 5xx ⇒ KHÔNG xóa cookie (lỗi tạm), để lần sau thử lại.
// Trang public chạy qua proxy chỉ để làm mới như trên (không bao giờ chuyển hướng): không có refresh_token thì đi thẳng, không đổi gì.
// Phiên Admin/NV (cookie `admin_session`, BE trượt 30 ngày): mỗi giờ tối đa một lần proxy gọi GET /admin/auth/me để BE gửi lại cookie với hạn mới
// (trang render ở server không đặt được cookie nên không dựa vào đó), đánh dấu bằng cookie `admin_renewed` (mốc thời gian).
// Quyền thật luôn kiểm ở server / backend.

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const ACCESS = "access_token";
const REFRESH = "refresh_token";
const ADMIN = "admin_session";
const ADMIN_MARK = "admin_renewed"; // mốc (ms) lần gia hạn phiên admin gần nhất từ proxy
const ADMIN_RENEW_MS = 60 * 60 * 1000; // tối đa một lần mỗi giờ
const REFRESH_AHEAD_SECONDS = 120; // JWT còn dưới 2 phút ⇒ làm mới trước
const LEGACY_REFRESH_PATH = "/api/v1/auth"; // cookie refresh cũ (trước T-077) nằm ở path này

/** Khu cần đăng nhập: thiếu phiên ⇒ về /dang-nhap. */
function needsLogin(pathname: string): boolean {
  return ["/tai-khoan", "/doi-mat-khau", "/admin", "/hoi-vien"].some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

/** Số giây còn lại của JWT (đọc `exp`, không cần xác minh chữ ký – backend mới là nơi xác minh). Không có / hỏng ⇒ -1. */
function secondsLeft(token: string | undefined): number {
  if (!token) return -1;
  try {
    const payload = token.split(".")[1] ?? "";
    const json = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/"))) as { exp?: unknown };
    return typeof json.exp === "number" ? json.exp - Date.now() / 1000 : -1;
  } catch {
    return -1;
  }
}

/** Origin của site mà trình duyệt đang dùng (backend chống CSRF bằng ALLOWED_ORIGINS): ưu tiên header do Caddy đặt. */
function siteOrigin(request: NextRequest): string {
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  const proto = request.headers.get("x-forwarded-proto")?.split(",")[0]?.trim();
  if (host) return `${proto ?? request.nextUrl.protocol.replace(":", "")}://${host.split(",")[0]?.trim()}`;
  return request.nextUrl.origin;
}

type Refreshed =
  | { kind: "ok"; setCookies: string[] } // cookie mới do backend cấp
  | { kind: "rejected"; setCookies: string[] } // refresh token không dùng được ⇒ cookie xóa
  | { kind: "error" }; // lỗi tạm

async function callBackend(path: string, headers: Record<string, string>, method = "POST"): Promise<Response | null> {
  try {
    return await fetch(`${BACKEND_URL}${path}`, { method, headers, signal: AbortSignal.timeout(5000), cache: "no-store" });
  } catch {
    return null;
  }
}

/** Cookie xóa phiên khách: lấy từ backend (đúng domain / path), kèm bản dự phòng nếu backend không trả lời. */
async function clearingCookies(): Promise<string[]> {
  const res = await callBackend("/api/v1/auth/logout", {});
  await res?.body?.cancel().catch(() => {});
  const fromBackend = res?.headers.getSetCookie() ?? [];
  const expire = "Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; SameSite=Lax";
  return [...fromBackend, `${ACCESS}=; Path=/; ${expire}`, `${REFRESH}=; Path=/; ${expire}`, `${REFRESH}=; Path=${LEGACY_REFRESH_PATH}; ${expire}`];
}

async function refreshSession(refreshToken: string, origin: string, forwardedFor: string | null): Promise<Refreshed> {
  const headers: Record<string, string> = { cookie: `${REFRESH}=${refreshToken}`, origin };
  if (forwardedFor) headers["x-forwarded-for"] = forwardedFor;
  const res = await callBackend("/api/v1/auth/refresh", headers);
  if (!res) return { kind: "error" };
  await res.body?.cancel().catch(() => {});
  if (res.ok) return { kind: "ok", setCookies: res.headers.getSetCookie() };
  if (res.status === 401) return { kind: "rejected", setCookies: await clearingCookies() };
  return { kind: "error" };
}

// Nhiều request cùng lúc (tải trang + prefetch + nhiều tab) mang CÙNG refresh token cũ: chỉ gọi backend một lần, các request
// còn lại dùng chung kết quả trong vài giây (trình duyệt chưa kịp nhận cookie mới). Chỉ là tối ưu: backend vẫn chịu được gọi trùng.
const SHARE_MS = 10_000;
const shared = new Map<string, { at: number; result: Promise<Refreshed> }>();

function refreshShared(refreshToken: string, origin: string, forwardedFor: string | null): Promise<Refreshed> {
  const now = Date.now();
  for (const [key, entry] of shared) if (now - entry.at > SHARE_MS) shared.delete(key);
  const hit = shared.get(refreshToken);
  if (hit) return hit.result;
  const result = refreshSession(refreshToken, origin, forwardedFor).then((r) => {
    if (r.kind === "error") shared.delete(refreshToken); // lỗi tạm: cho request sau thử lại ngay
    return r;
  });
  shared.set(refreshToken, { at: now, result });
  return result;
}

type AdminRenewal = { kind: "renewed"; setCookies: string[] } | { kind: "rejected" } | { kind: "error" };

// Nhiều request cùng lúc (tải trang + RSC) chỉ gọi BE một lần cho cùng một phiên.
const adminShared = new Map<string, { at: number; result: Promise<AdminRenewal> }>();

async function renewAdminOnce(adminToken: string, forwardedFor: string | null): Promise<AdminRenewal> {
  const headers: Record<string, string> = { cookie: `${ADMIN}=${adminToken}` };
  if (forwardedFor) headers["x-forwarded-for"] = forwardedFor;
  const res = await callBackend("/api/v1/admin/auth/me", headers, "GET");
  if (!res) return { kind: "error" };
  await res.body?.cancel().catch(() => {});
  if (res.ok) return { kind: "renewed", setCookies: res.headers.getSetCookie() };
  if (res.status === 401) return { kind: "rejected" }; // hết phiên: trang tự xử lý (về /dang-nhap kèm lý do)
  return { kind: "error" };
}

function renewAdmin(adminToken: string, forwardedFor: string | null): Promise<AdminRenewal> {
  const now = Date.now();
  for (const [key, entry] of adminShared) if (now - entry.at > SHARE_MS) adminShared.delete(key);
  const hit = adminShared.get(adminToken);
  if (hit) return hit.result;
  const result = renewAdminOnce(adminToken, forwardedFor).then((r) => {
    if (r.kind === "error") adminShared.delete(adminToken);
    return r;
  });
  adminShared.set(adminToken, { at: now, result });
  return result;
}

/** Ghi / xóa cookie (theo tên) trong chuỗi header `Cookie` của request. Giá trị rỗng ⇒ xóa. */
function withCookies(cookieHeader: string, updates: Map<string, string>): string {
  const kept = cookieHeader
    .split(/;\s*/)
    .filter((part) => part && !updates.has(part.split("=")[0] ?? ""))
    .join("; ");
  const added = [...updates].filter(([, value]) => value).map(([name, value]) => `${name}=${value}`);
  return [kept, ...added].filter(Boolean).join("; ");
}

/** Cặp tên=giá trị đầu tiên của mỗi Set-Cookie (giá trị rỗng hoặc Max-Age=0 ⇒ cookie bị xóa). */
function cookieUpdates(setCookies: string[]): Map<string, string> {
  const updates = new Map<string, string>();
  for (const line of setCookies) {
    const [pair = "", ...attrs] = line.split(";");
    const eq = pair.indexOf("=");
    if (eq <= 0) continue;
    const name = pair.slice(0, eq).trim();
    if (name !== ACCESS && name !== REFRESH && name !== ADMIN) continue;
    const expired = attrs.some((a) => /^\s*max-age\s*=\s*0\s*$/i.test(a));
    // Backend vừa cấp refresh token mới (path "/") vừa xóa bản cũ (path cũ) cùng tên: lệnh xóa không được đè giá trị mới
    if (expired && updates.get(name)) continue;
    updates.set(name, expired ? "" : pair.slice(eq + 1).trim());
  }
  return updates;
}

export async function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const isAdmin = pathname.startsWith("/admin");
  const protectedPath = needsLogin(pathname);

  let setCookies: string[] = [];
  let cookieHeader: string | null = null; // chỉ đặt khi cần đổi cookie của request

  // Khu quản trị: gia hạn phiên `admin_session` tối đa mỗi giờ một lần
  const adminToken = request.cookies.get(ADMIN)?.value;
  if (isAdmin && adminToken) {
    const last = Number(request.cookies.get(ADMIN_MARK)?.value ?? 0);
    if (!(Date.now() - last < ADMIN_RENEW_MS)) {
      const result = await renewAdmin(adminToken, request.headers.get("x-forwarded-for"));
      if (result.kind !== "error") {
        const mark = `${ADMIN_MARK}=${Date.now()}; Path=/; Max-Age=${30 * 86400}; HttpOnly; SameSite=Lax${request.nextUrl.protocol === "https:" || request.headers.get("x-forwarded-proto") === "https" ? "; Secure" : ""}`;
        setCookies = [...(result.kind === "renewed" ? result.setCookies : []), mark];
        const updates = cookieUpdates(setCookies);
        updates.set(ADMIN_MARK, String(Date.now()));
        cookieHeader = withCookies(request.headers.get("cookie") ?? "", updates);
      }
    }
  }

  // Khách / hội viên dùng JWT: làm mới nếu cần (phiên admin không đụng tới)
  if (!isAdmin && !request.cookies.has(ADMIN)) {
    const refreshToken = request.cookies.get(REFRESH)?.value;
    if (refreshToken && secondsLeft(request.cookies.get(ACCESS)?.value) < REFRESH_AHEAD_SECONDS) {
      const result = await refreshShared(refreshToken, siteOrigin(request), request.headers.get("x-forwarded-for"));
      if (result.kind !== "error") {
        setCookies = result.setCookies;
        cookieHeader = withCookies(request.headers.get("cookie") ?? "", cookieUpdates(setCookies));
        if (result.kind === "rejected" && protectedPath) {
          const login = new URL("/dang-nhap", request.url);
          login.searchParams.set("next", pathname + search);
          login.searchParams.set("ly-do", "het-han");
          const redirect = NextResponse.redirect(login);
          for (const line of setCookies) redirect.headers.append("set-cookie", line);
          return redirect;
        }
      }
    }
  }

  const hasSession = request.cookies.has(isAdmin ? ADMIN : ACCESS) || (cookieHeader !== null && /(?:^|;\s*)access_token=/.test(cookieHeader));
  if (protectedPath && !hasSession) {
    const login = new URL("/dang-nhap", request.url);
    login.searchParams.set("next", pathname + search);
    return NextResponse.redirect(login);
  }

  if (!protectedPath && cookieHeader === null) return NextResponse.next(); // trang public không đổi gì

  const headers = new Headers(request.headers);
  // Layout khu hội viên cần biết đường dẫn đang mở để quay lại sau khi đăng nhập lại
  if (protectedPath) headers.set("x-pathname", pathname + search);
  if (cookieHeader !== null) headers.set("cookie", cookieHeader);
  const response = NextResponse.next({ request: { headers } });
  for (const line of setCookies) response.headers.append("set-cookie", line);
  return response;
}

export const config = {
  // Khu cần đăng nhập + mọi trang public (header hiện tài khoản sau 30 phút). Bỏ qua API, tệp tĩnh và icon app.
  matcher: ["/tai-khoan/:path*", "/doi-mat-khau", "/admin/:path*", "/hoi-vien/:path*", "/((?!api/|_next/|pwa-icon/|.*\\..*).*)"],
};
