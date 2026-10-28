import "client-only";
import { useSyncExternalStore } from "react";
import { formatCountdown } from "@/lib/format";
import { api, errorDetail, errorMessage } from "./client";

// --- Đăng nhập / đăng xuất ---

// E-001 sai thông tin, E-002 tạm khóa, E-008 IP bị chặn, google_* đăng nhập Google
type LoginErrorCode =
  | "E-001"
  | "E-002"
  | "E-008"
  | "google_invalid"
  | "google_disabled"
  | "google_unavailable"
  | "network"
  | "unavailable";

type LoginResult =
  | { ok: true; kind: "admin" | "customer" }
  | { ok: false; code: LoginErrorCode; retryAfter?: number };

const KNOWN_CODES = new Set<string>([
  "E-001",
  "E-002",
  "E-008",
  "google_invalid",
  "google_disabled",
  "google_unavailable",
]);

function toFailure(error: unknown): Extract<LoginResult, { ok: false }> {
  const { code, retry_after } = errorDetail(error);
  const known = code && KNOWN_CODES.has(code) ? (code as LoginErrorCode) : "unavailable";
  return { ok: false, code: known, retryAfter: retry_after };
}

// Đăng nhập chung Admin/nhân viên/khách; `kind` cho biết đi tới khu nào
export async function signIn(body: { login: string; password: string }): Promise<LoginResult> {
  try {
    const { data, error } = await api.POST("/api/v1/auth/sign-in", { body });
    return data ? { ok: true, kind: data.kind } : toFailure(error);
  } catch {
    return { ok: false, code: "network" };
  }
}

// Khách đăng nhập bằng ID token của nút Google
export async function googleSignIn(credential: string): Promise<LoginResult> {
  try {
    const { data, error } = await api.POST("/api/v1/auth/google", { body: { credential } });
    return data ? { ok: true, kind: data.kind } : toFailure(error);
  } catch {
    return { ok: false, code: "network" };
  }
}

// Thu hồi phiên quản trị trên máy này
export async function adminLogout(): Promise<void> {
  await api.POST("/api/v1/admin/auth/logout").catch(() => {});
}

// --- OTP: quên mật khẩu, xác minh SĐT ---

export type OtpFailure = {
  ok: false;
  // Mã backend, `invalid` (422) hoặc `network`/`unavailable`
  code: string;
  retryAfter?: number;
  attemptsLeft?: number;
  // 422: câu lỗi của backend
  message?: string;
};

async function callOtpApi<T>(
  request: () => Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<({ ok: true } & T) | OtpFailure> {
  try {
    const { data, error, response } = await request();
    // 204 (confirm) không có body nhưng vẫn là thành công
    if (response.ok) return { ok: true, ...(data as T) };
    const detail = errorDetail(error);
    const isInvalid = response.status === 422;
    return {
      ok: false,
      code: isInvalid ? "invalid" : (detail.code ?? "unavailable"),
      retryAfter: detail.retry_after ?? (Number(response.headers.get("Retry-After")) || undefined),
      attemptsLeft: detail.attempts_left,
      message: isInvalid ? errorMessage(error, "") || undefined : undefined,
    };
  } catch {
    return { ok: false, code: "network" };
  }
}

// Gửi mã quên mật khẩu (luôn 202 với SĐT hợp lệ, không lộ SĐT có tài khoản)
export const requestReset = (phone: string) =>
  callOtpApi(() => api.POST("/api/v1/auth/password-reset/request", { body: { phone } }));
// Kiểm mã quên mật khẩu, trả `reset_token`
export const verifyOtp = (phone: string, otp: string) =>
  callOtpApi(() => api.POST("/api/v1/auth/password-reset/verify", { body: { phone, otp } }));
// Đặt mật khẩu mới bằng `reset_token`
export const confirmReset = (resetToken: string, password: string) =>
  callOtpApi(() =>
    api.POST("/api/v1/auth/password-reset/confirm", { body: { reset_token: resetToken, password } }),
  );
// Gửi mã xác minh SĐT cho khách chưa có SĐT (đăng nhập Google)
export const requestPhoneVerify = (phone: string) =>
  callOtpApi(() => api.POST("/api/v1/auth/phone/request", { body: { phone } }));
// Gắn SĐT vào tài khoản; `merged` ⇒ đã chuyển sang tài khoản sẵn có của số đó
export const verifyPhone = (phone: string, otp: string) =>
  callOtpApi(() => api.POST("/api/v1/auth/phone/verify", { body: { phone, otp } }));

// Mốc (ms) được bấm "Gửi lại mã"; 429 vẫn có mốc vì mã trước còn dùng được; lỗi khác ⇒ null
export function otpResendAt(result: { ok: true; resend_after: number } | OtpFailure): number | null {
  if (result.ok) return Date.now() + result.resend_after * 1000;
  if (result.code === "otp_rate_limited") return Date.now() + (result.retryAfter ?? 60) * 1000;
  return null;
}

type OtpErrorTexts = Record<string, string> & {
  otp_invalid: string;
  otp_rate_limited: string;
  unavailable: string;
};

// Lỗi OTP ⇒ câu hiển thị theo mã; mã không có câu riêng ⇒ câu chung
export function otpErrorText(errors: OtpErrorTexts, failure: OtpFailure): string {
  if (failure.code === "otp_invalid") {
    return errors.otp_invalid.replace("{n}", String(failure.attemptsLeft ?? 0));
  }
  if (failure.code === "otp_rate_limited") {
    return errors.otp_rate_limited.replace("{time}", formatCountdown(failure.retryAfter ?? 60));
  }
  return Object.hasOwn(errors, failure.code) ? errors[failure.code] : errors.unavailable;
}

// --- sessionStorage giữa 3 màn quên mật khẩu (không đưa lên URL) ---

export const RESET_PHONE_KEY = "pw-reset-phone";
export const RESET_TOKEN_KEY = "pw-reset-token";
export const RESET_RESEND_KEY = "pw-reset-resend-at";

// Ghi/xóa một giá trị phiên quên mật khẩu
export function saveResetValue(key: string, value: string | null) {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, value);
  } catch {
    // Trình duyệt chặn bộ nhớ ⇒ màn sau báo làm lại từ đầu
  }
}

const noopSubscribe = () => () => {};

// Đọc giá trị phiên quên mật khẩu; máy chủ trả `undefined` (chưa biết)
export function useResetValue(key: string): string | null | undefined {
  return useSyncExternalStore(
    noopSubscribe,
    () => {
      try {
        return sessionStorage.getItem(key);
      } catch {
        return null;
      }
    },
    () => undefined,
  );
}
