import "client-only";
import { api, errorDetail, looseApi } from "./client";

// --- Đăng nhập / đăng xuất (T-013) ---

// Mã giao diện: E-001 sai thông tin, E-002 tạm khóa tài khoản, E-008 IP bị chặn, google_* đăng nhập Google.
type LoginErrorCode =
  | "E-001"
  | "E-002"
  | "E-008"
  | "google_invalid"
  | "google_disabled"
  | "google_unavailable"
  | "network"
  | "unavailable";

export type LoginResult =
  | { ok: true; kind: "admin" | "customer" }
  | { ok: false; code: LoginErrorCode; retryAfter?: number };

// Mã backend (E-AUTH-*) → mã câu chữ trong i18n/messages/vi.json
const CODE_MAP: Record<string, LoginErrorCode> = {
  "E-AUTH-10": "E-001",
  "E-AUTH-11": "E-002",
  "E-AUTH-12": "E-008",
  "E-AUTH-19": "google_disabled",
  "E-AUTH-20": "google_invalid",
  "E-AUTH-21": "google_unavailable",
};

function toFailure(error: unknown, response?: Response): Extract<LoginResult, { ok: false }> {
  const { code, retry_after } = errorDetail(error);
  const header = Number(response?.headers.get("Retry-After")) || undefined;
  return { ok: false, code: (code && CODE_MAP[code]) || "unavailable", retryAfter: retry_after ?? header };
}

// Đăng nhập chung Admin/nhân viên/khách; `kind` cho biết đi tới khu nào
export async function signIn(body: { login: string; password: string }): Promise<LoginResult> {
  try {
    const { data, error, response } = await api.POST("/api/v1/auth/sign-in", { body });
    return data ? { ok: true, kind: data.kind } : toFailure(error, response);
  } catch {
    return { ok: false, code: "network" };
  }
}

// Khách đăng nhập bằng ID token của nút Google (endpoint có ở mốc 2 của BE; tới lúc đó gọi không ràng kiểu)
export async function googleSignIn(credential: string): Promise<LoginResult> {
  try {
    const { data, error, response } = await looseApi.POST("/api/v1/auth/google", { body: { credential } });
    return data ? { ok: true, kind: (data as { kind: "admin" | "customer" }).kind } : toFailure(error, response);
  } catch {
    return { ok: false, code: "network" };
  }
}

// Thu hồi phiên quản trị trên máy này
export async function adminLogout(): Promise<void> {
  await api.POST("/api/v1/admin/auth/logout").catch(() => {});
}
