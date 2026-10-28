// Kiểu của trang Cài đặt thanh toán (T-012 §API). Dựng theo spec; khi BACKEND handoff và `schema.d.ts` có `/payments/settings`,
// đổi sang `components["schemas"][...]` và thêm kiểm tra lúc biên dịch như `booking-engine/types.ts`.

export type MissingField = "bank" | "account_number" | "account_name" | "webhook_secret";

export type PaymentSettings = {
  bank_code: string | null;
  bank_name: string | null;
  account_number: string | null;
  account_name: string | null;
  online_toggle: boolean;
  online_enabled: boolean;
  missing: MissingField[];
  secret_set: boolean;
  secret_last4: string | null;
  webhook_url: string;
  pay_code_hint: string;
  last_webhook_at: string | null;
  updated_at: string | null;
  updated_by_label: string | null;
  pending_checkouts: number;
  simulate_enabled: boolean;
};

export type BankOption = { code: string; short_name: string; name: string };

export const MISSING_LABEL: Record<MissingField, string> = {
  bank: "Ngân hàng",
  account_number: "Số tài khoản",
  account_name: "Chủ tài khoản",
  webhook_secret: "Khóa bí mật webhook",
};
