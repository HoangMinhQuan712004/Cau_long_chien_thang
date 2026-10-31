import "client-only";
import { useSyncExternalStore } from "react";
import { formatCountdown } from "@/lib/format";
import { destination } from "@/lib/safe-next";
import { api, errorDetail, errorMessage } from "./client";
import type { operations } from "./schema";

// --- Đăng nhập / đăng xuất (T-013) ---

// Mã giao diện: E-001 sai thông tin, E-002 tạm khóa tài khoản, E-008 IP bị chặn, google_* đăng nhập Google.
type LoginErrorCode =
  | "E-001"
  | "E-002"
  | "E-008"
  | "google_invalid"
  | "google_disabled"
  | "google_unavailable"
  | "initial_expired"
  | "network"
  | "unavailable";

export type LoginResult =
  // `mustChangePassword`: khách hội viên còn mật khẩu ban đầu (= SĐT) ⇒ đi thẳng /doi-mat-khau (T-015)
  | { ok: true; kind: "admin" | "member"; mustChangePassword: boolean }
  | { ok: false; code: LoginErrorCode; retryAfter?: number };

/** Mã BE: mật khẩu ban đầu hết hạn (đăng nhập, đổi mật khẩu lần đầu). */
export const INITIAL_PASSWORD_EXPIRED = "E-AUTH-30";

// Mã backend (E-AUTH-*) → mã câu chữ trong i18n/messages/vi.json
const CODE_MAP: Record<string, LoginErrorCode> = {
  "E-AUTH-10": "E-001",
  "E-AUTH-11": "E-002",
  "E-AUTH-12": "E-008",
  "E-AUTH-19": "google_disabled",
  "E-AUTH-20": "google_invalid",
  "E-AUTH-21": "google_unavailable",
  // T-015: mật khẩu ban đầu (= SĐT) quá 3 ngày ⇒ phải dùng Quên mật khẩu (mã BE dự kiến, chờ chốt)
  [INITIAL_PASSWORD_EXPIRED]: "initial_expired",
};

function toFailure(error: unknown, response?: Response): Extract<LoginResult, { ok: false }> {
  const { code, retry_after } = errorDetail(error);
  const header = Number(response?.headers.get("Retry-After")) || undefined;
  return { ok: false, code: (code && CODE_MAP[code]) || "unavailable", retryAfter: retry_after ?? header };
}

// Kết quả đăng nhập thành công (Admin / khách)
function toSuccess(data: SignInData): LoginResult {
  return { ok: true, kind: data.kind, mustChangePassword: data.kind === "member" && data.account.must_change_password };
}
// Lấy theo response của API (không phụ thuộc tên schema của từng nhánh)
type SignInData = operations["sign_in_api_v1_auth_sign_in_post"]["responses"][200]["content"]["application/json"];

// Đăng nhập chung Admin/nhân viên/khách; `kind` cho biết đi tới khu nào
export async function signIn(body: { login: string; password: string }): Promise<LoginResult> {
  try {
    const { data, error, response } = await api.POST("/api/v1/auth/sign-in", { body });
    return data ? toSuccess(data) : toFailure(error, response);
  } catch {
    return { ok: false, code: "network" };
  }
}

// Khách đăng nhập bằng ID token của nút Google
export async function googleSignIn(credential: string): Promise<LoginResult> {
  try {
    const { data, error, response } = await api.POST("/api/v1/auth/google", { body: { credential } });
    return data ? toSuccess(data) : toFailure(error, response);
  } catch {
    return { ok: false, code: "network" };
  }
}

// Thu hồi phiên quản trị trên máy này
export async function adminLogout(): Promise<void> {
  await api.POST("/api/v1/admin/auth/logout").catch(() => {});
}

// --- OTP: quên mật khẩu, xác minh SĐT (T-013) ---

export type OtpFailure = {
  ok: false;
  // Mã giao diện (otp_*, phone_unusable…), mã backend chưa có câu riêng, `invalid` (422) hoặc `network`/`unavailable`
  code: string;
  retryAfter?: number;
  attemptsLeft?: number;
  // 422 hoặc mã không có câu riêng ở i18n: câu của backend
  message?: string;
};

// Mã backend (E-AUTH-*) → mã câu chữ trong i18n/messages/vi.json
const OTP_CODE_MAP: Record<string, string> = {
  "E-AUTH-13": "otp_rate_limited",
  "E-AUTH-14": "otp_invalid",
  "E-AUTH-15": "otp_expired",
  "E-AUTH-16": "reset_token_invalid",
  "E-AUTH-18": "phone_unusable",
};

export async function callOtpApi<T>(
  request: () => Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<({ ok: true } & T) | OtpFailure> {
  try {
    const { data, error, response } = await request();
    // 204 (confirm) không có body nhưng vẫn là thành công
    if (response.ok) return { ok: true, ...(data as T) };
    const detail = errorDetail(error);
    const isInvalid = response.status === 422;
    const mapped = detail.code ? OTP_CODE_MAP[detail.code] : undefined;
    return {
      ok: false,
      code: isInvalid ? "invalid" : (mapped ?? detail.code ?? "unavailable"),
      retryAfter: detail.retry_after ?? (Number(response.headers.get("Retry-After")) || undefined),
      attemptsLeft: detail.attempts_left,
      message: isInvalid || !mapped ? errorMessage(error, "") || undefined : undefined,
    };
  } catch {
    return { ok: false, code: "network" };
  }
}

// Gửi mã quên mật khẩu (luôn 202 với SĐT hợp lệ, không lộ SĐT có tài khoản); chế độ thử trả thêm `test_otp`
export const requestReset = (phone: string) =>
  callOtpApi(() => api.POST("/api/v1/auth/password-reset/request", { body: { phone } }));
// Kiểm mã quên mật khẩu, trả `reset_token`
export const verifyOtp = (phone: string, otp: string) =>
  callOtpApi(() => api.POST("/api/v1/auth/password-reset/verify", { body: { phone, otp } }));
// Đặt mật khẩu mới bằng `reset_token`
export const confirmReset = (resetToken: string, password: string) =>
  callOtpApi(() => api.POST("/api/v1/auth/password-reset/confirm", { body: { reset_token: resetToken, password } }));
// Gửi mã xác minh SĐT cho khách chưa có SĐT (đăng nhập Google)
export const requestPhoneVerify = (phone: string) =>
  callOtpApi(() => api.POST("/api/v1/auth/phone/request", { body: { phone } }));
// Gắn SĐT vào tài khoản; `merged` ⇒ đã chuyển sang tài khoản sẵn có của số đó
export const verifyPhone = (phone: string, otp: string) =>
  callOtpApi(() => api.POST("/api/v1/auth/phone/verify", { body: { phone, otp } }));

// Đăng ký 2 bước (T-021): gửi mã OTP tới SĐT (chưa tạo tài khoản) ⇒ nhập đúng mã thì tạo tài khoản + hội viên + đăng nhập luôn
export const registerRequest = (body: { full_name: string; phone: string; password: string }) =>
  callOtpApi(() => api.POST("/api/v1/auth/register/request", { body }));
export const registerVerify = (phone: string, otp: string) =>
  callOtpApi(() => api.POST("/api/v1/auth/register/verify", { body: { phone, otp } }));

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

// Lỗi OTP ⇒ câu hiển thị theo mã; mã không có câu riêng ⇒ câu của backend, rồi câu chung
export function otpErrorText(errors: OtpErrorTexts, failure: OtpFailure): string {
  if (failure.code === "otp_invalid") {
    return errors.otp_invalid.replace("{n}", String(failure.attemptsLeft ?? 0));
  }
  if (failure.code === "otp_rate_limited") {
    return errors.otp_rate_limited.replace("{time}", formatCountdown(failure.retryAfter ?? 60));
  }
  if (Object.hasOwn(errors, failure.code)) return errors[failure.code];
  return failure.message ?? errors.unavailable;
}

// --- sessionStorage giữa 3 màn quên mật khẩu (không đưa lên URL) ---

export const RESET_PHONE_KEY = "pw-reset-phone";
export const RESET_TOKEN_KEY = "pw-reset-token";
export const RESET_RESEND_KEY = "pw-reset-resend-at";
// Mã thử (OTP_TEST_MODE) của lần gửi gần nhất, để màn nhập mã hiện hộp "Mã thử"
export const RESET_TEST_OTP_KEY = "pw-reset-test-otp";

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

/** Đích sau đăng nhập của khách: có ?next thì theo next; không thì hội viên (đã liên kết hồ sơ) vào khu hội viên, còn lại về "/" (T-016 AC3). */
export async function memberDestination(next: string): Promise<string> {
  if (next) return destination("member", next);
  try {
    const { data } = await api.GET("/api/v1/auth/me");
    if ((data as { is_member?: boolean } | undefined)?.is_member) return "/hoi-vien/ho-so";
  } catch {
    /* không đọc được hồ sơ ⇒ về trang chủ */
  }
  return "/";
}
