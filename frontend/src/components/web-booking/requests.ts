import "client-only";
import { callOtpApi } from "@/lib/api/auth";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { toApiError, type ApiError } from "@/lib/api/write";
import type { Checkout, Lookup, WebCalendar } from "./types";

// Lời gọi API công khai của web khách (không cần đăng nhập). Ghi: dùng `write()` (Idempotency-Key) ở nơi gọi.

export type Read<T> = { ok: true; data: T } | { ok: false; error: ApiError };

async function read<T>(call: () => Promise<{ data?: T; error?: unknown; response: Response }>): Promise<Read<T>> {
  try {
    const { data, error, response } = await call();
    if (response.ok && data !== undefined) return { ok: true, data };
    return { ok: false, error: toApiError(error, response.status) };
  } catch {
    return { ok: false, error: { status: 0, code: "E-017", message: "Mất kết nối. Vui lòng thử lại.", extra: {} } };
  }
}

export const getWebCalendar = (date: string) =>
  read<WebCalendar>(() => api.GET("/api/v1/web/booking/calendar", { params: { query: { date } } }));

export const getCheckout = (token: string) =>
  read<Checkout>(() => api.GET("/api/v1/web/booking/checkouts/{token}", { params: { path: { token } } }));

export type CheckoutBody = components["schemas"]["CheckoutIn"];

/** Gọi qua `write((key) => sendCheckout(key, body))`. */
export const sendCheckout = (key: string, body: CheckoutBody) =>
  api.POST("/api/v1/web/booking/checkouts", { body, headers: { "Idempotency-Key": key } });

export const lookupBooking = (code: string, phone: string) =>
  read<Lookup>(() => api.POST("/api/v1/web/booking/lookup", { body: { code, phone } }));

// ---- Xác minh SĐT bằng OTP trước khi giữ chỗ (T-013 AC25) ----
export const requestBookingPhone = (phone: string) =>
  callOtpApi(() => api.POST("/api/v1/web/booking/phone/request", { body: { phone } }));

export const verifyBookingPhone = (phone: string, otp: string) =>
  callOtpApi(() => api.POST("/api/v1/web/booking/phone/verify", { body: { phone, otp } }));
