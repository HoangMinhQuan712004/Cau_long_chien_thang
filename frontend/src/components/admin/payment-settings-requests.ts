import "client-only";
import { api, looseApi } from "@/lib/api/client";
import { toApiError, type ApiError } from "@/lib/api/write";
import type { BankTransaction } from "@/components/web-booking/types";
import type { PaymentSettings } from "./payment-settings-types";

// TODO(T-012): khi `schema.d.ts` có `/payments/settings`, chuyển `looseApi` sang `api`.

export type Read<T> = { ok: true; data: T } | { ok: false; error: ApiError };

export async function getPaymentSettings(): Promise<Read<PaymentSettings>> {
  try {
    const { data, error, response } = await looseApi.GET("/api/v1/payments/settings", {});
    if (response.ok && data) return { ok: true, data: data as PaymentSettings };
    return { ok: false, error: toApiError(error, response.status) };
  } catch {
    return { ok: false, error: { status: 0, code: "E-017", message: "Mất kết nối. Vui lòng thử lại.", extra: {} } };
  }
}

export type SaveBody = {
  bank_code: string;
  account_number: string;
  account_name: string;
  online_toggle: boolean;
  /** Bỏ qua / null = giữ khóa hiện tại. */
  webhook_secret?: string | null;
  current_password: string;
};

/** Gọi qua `write((key) => sendSavePaymentSettings(key, body))`. */
export const sendSavePaymentSettings = (key: string, body: SaveBody) =>
  looseApi.PUT("/api/v1/payments/settings", { body, headers: { "Idempotency-Key": key } });

/** Giả lập tiền về (chỉ môi trường thử). Trả `BankTransactionOut`. */
export const sendSimulate = (key: string, pay_ref: string, amount: number) =>
  api.POST("/api/v1/payments/dev/simulate", { body: { pay_ref, amount }, headers: { "Idempotency-Key": key } });

export type SimulateResult = BankTransaction;
