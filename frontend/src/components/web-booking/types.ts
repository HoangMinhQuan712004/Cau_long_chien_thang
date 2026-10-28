// Kiểu dữ liệu của web khách (T-008 §API contract). Dựng theo spec; khi BACKEND handoff và `schema.d.ts` có đủ
// thì thêm kiểm tra lúc biên dịch như `booking-engine/types.ts` (SchemaContract).

export type SlotState = "free" | "booked" | "event" | "closed";

export type WebSlot = {
  start_hour: number;
  state: SlotState;
  /** Chỉ có khi `free`. */
  price?: number;
  band?: "offpeak" | "peak";
  /** Chỉ có khi `event`. */
  taken?: number;
  capacity?: number;
};

export type WebResource = { code: string; name: string; slots: WebSlot[] };

export type WebCalendar = {
  date: string;
  server_now: string;
  online_enabled: boolean;
  hold_minutes: number;
  columns: number[];
  resources: WebResource[];
};

export type Bank = {
  bank_name: string;
  account_number: string;
  account_name: string;
  qr_url: string;
};

export type CheckoutItem = {
  code: string;
  resource_name: string;
  play_date: string;
  start_time: string;
  end_time: string;
  hours: number;
  amount: number;
};

export type Checkout = {
  /** Chỉ có ở response tạo. */
  token?: string;
  status: "pending" | "paid" | "expired";
  expires_at: string;
  server_now: string;
  amount: number;
  paid_amount: number;
  paid_at: string | null;
  pay_ref: string;
  bank: Bank | null;
  customer: { full_name: string; phone_masked: string };
  items: CheckoutItem[];
};

export type LookupStatus = "paid" | "unpaid" | "uncollectible" | "pending" | "expired";

export type Lookup = {
  code: string;
  status: LookupStatus;
  resource_name: string;
  play_date: string;
  start_time: string;
  end_time: string;
  hours: number;
  customer_name: string;
  phone_masked: string;
  amount: number;
  payment_method_label?: string | null;
  paid_at?: string | null;
  pending?: { expires_at: string; server_now: string; pay_ref: string; amount: number; bank: Bank | null } | null;
};

/** Ô đã chọn trên lưới: sân + giờ bắt đầu. */
export type Cell = { code: string; hour: number };

export const MAX_CELLS = 16;

/** Khóa sessionStorage do màn "Hết thời gian giữ chỗ" ghi để "Đặt lại" chọn sẵn các ô cũ nếu còn trống. */
export const RESTORE_KEY = "wk-restore-v1";

export type BankTransaction = {
  id: number;
  provider: string;
  provider_txn_id: string;
  received_at: string;
  transaction_at: string;
  amount: number;
  content: string;
  code: string | null;
  outcome: "applied" | "partial" | "refund_needed" | "unmatched" | "ignored";
  refund_amount: number;
  booking_codes: string[];
  resolved_at: string | null;
  resolved_by_label: string | null;
  note: string | null;
};
