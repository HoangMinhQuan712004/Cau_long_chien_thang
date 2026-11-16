import type { components } from "@/lib/api/schema";

// Kiểu của trang Cài đặt thanh toán (T-012): lấy thẳng từ `schema.d.ts` (sinh từ backend).
type S = components["schemas"];

export type PaymentSettings = S["PaymentSettingsOut"];
export type PaymentSettingsBody = S["PaymentSettingsIn"];
export type BankOption = S["BankOut"];
export type MissingField = PaymentSettings["missing"][number];

export const MISSING_LABEL: Record<MissingField, string> = {
  bank: "Ngân hàng",
  account_number: "Số tài khoản",
  account_name: "Chủ tài khoản",
  webhook_secret: "Khóa bí mật webhook",
};
