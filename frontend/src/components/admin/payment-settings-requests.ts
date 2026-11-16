import "client-only";
import { api } from "@/lib/api/client";
import { toApiError, type ApiError } from "@/lib/api/write";
import type { PaymentSettings, PaymentSettingsBody } from "./payment-settings-types";

export type Read<T> = { ok: true; data: T } | { ok: false; error: ApiError };

export async function getPaymentSettings(): Promise<Read<PaymentSettings>> {
  try {
    const { data, error, response } = await api.GET("/api/v1/payments/settings");
    if (response.ok && data) return { ok: true, data };
    return { ok: false, error: toApiError(error, response.status) };
  } catch {
    return { ok: false, error: { status: 0, code: "E-017", message: "Mất kết nối. Vui lòng thử lại.", extra: {} } };
  }
}

/** Gọi qua `write((key) => sendSavePaymentSettings(key, body))`. */
export const sendSavePaymentSettings = (key: string, body: PaymentSettingsBody) =>
  api.PUT("/api/v1/payments/settings", { body, headers: { "Idempotency-Key": key } });

/** Giả lập tiền về (chỉ môi trường thử). Trả `BankTransactionOut`. */
export const sendSimulate = (key: string, pay_ref: string, amount: number) =>
  api.POST("/api/v1/payments/dev/simulate", { body: { pay_ref, amount }, headers: { "Idempotency-Key": key } });
