import "client-only";
import { looseApi } from "@/lib/api/client";
import { toApiError, type ApiError } from "@/lib/api/write";
import type { BankTransaction, Checkout, Lookup, WebCalendar } from "./types";

// Lời gọi API công khai của web khách (không cần đăng nhập). Ghi: dùng `write()` (Idempotency-Key) ở nơi gọi.
// TODO(T-008): khi `schema.d.ts` có các đường dẫn này (BACKEND handoff), chuyển từ `looseApi` sang `api`.

export type Read<T> = { ok: true; data: T } | { ok: false; error: ApiError };

async function read<T>(call: () => Promise<{ data?: unknown; error?: unknown; response: Response }>): Promise<Read<T>> {
  try {
    const { data, error, response } = await call();
    if (response.ok && data !== undefined) return { ok: true, data: data as T };
    return { ok: false, error: toApiError(error, response.status) };
  } catch {
    return { ok: false, error: { status: 0, code: "E-017", message: "Mất kết nối. Vui lòng thử lại.", extra: {} } };
  }
}

const P = "/api/v1/web/booking";

export const getWebCalendar = (date: string) =>
  read<WebCalendar>(() => looseApi.GET(`${P}/calendar`, { params: { query: { date } } }));

export const getCheckout = (token: string) =>
  read<Checkout>(() => looseApi.GET(`${P}/checkouts/{token}`, { params: { path: { token } } }));

export type CheckoutBody = {
  date: string;
  slots: { resource_code: string; start_hour: number }[];
  full_name: string;
  phone: string;
  note?: string;
};

/** Gọi qua `write((key) => sendCheckout(key, body))`. */
export const sendCheckout = (key: string, body: CheckoutBody) =>
  looseApi.POST(`${P}/checkouts`, { body, headers: { "Idempotency-Key": key } });

export const lookupBooking = (code: string, phone: string) =>
  read<Lookup>(() => looseApi.POST(`${P}/lookup`, { body: { code, phone } }));

// ---- Quản trị: Tiền về cần xử lý ----
export const getBankTransactions = (needsAction: boolean) =>
  read<BankTransaction[]>(() =>
    looseApi.GET("/api/v1/payments/bank-transactions", { params: { query: { needs_action: needsAction, limit: 100 } } }),
  );

export const sendResolve = (key: string, id: number, note: string) =>
  looseApi.POST("/api/v1/payments/bank-transactions/{id}/resolve", {
    params: { path: { id } },
    body: { note },
    headers: { "Idempotency-Key": key },
  });
