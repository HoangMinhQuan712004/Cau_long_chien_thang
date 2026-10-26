// Kiểu dữ liệu của booking engine (T-006 §4). Phản chiếu DTO backend `booking_engine/dto.py`.
// TODO(T-006): khi BACKEND handoff và `schema.d.ts` có các kiểu này, đổi sang `components["schemas"][...]`.

export type PaymentStatus = "unpaid" | "paid" | "uncollectible";
export type PaymentMethod = "cash" | "transfer" | "online_transfer";
export type Source = "counter" | "online";

export type CalendarResource = {
  code: string;
  name: string;
  type: string;
  is_active: boolean;
  /** Giờ bắt đầu các ô Xám (không bán) của sân này. */
  off_hours: number[];
};

export type CalendarBlock = {
  type: "booking" | "session" | "hold";
  code: string | null;
  resource_codes: string[];
  start_time: string;
  end_time: string;
  start_hour: number;
  end_hour: number;
  payment_status?: PaymentStatus | null;
  customer_name?: string | null;
  phone_masked?: string | null;
  source?: Source | null;
  name?: string | null;
  taken?: number | null;
  capacity?: number | null;
  is_full?: boolean | null;
  unpaid_tickets?: number | null;
  expires_at?: string | null;
};

export type Calendar = {
  date: string;
  now: string;
  is_past: boolean;
  /** Giờ bắt đầu từng cột (khung 1 giờ), liền nhau. */
  columns: number[];
  resources: CalendarResource[];
  blocks: CalendarBlock[];
  unpaid_count: number;
  can: { counter_book: boolean; create_session: boolean };
};

export type QuoteItem = {
  start_time: string;
  end_time: string;
  band: "offpeak" | "partial" | "peak";
  label: string;
  price: number;
};

export type Quote = {
  resource_code: string;
  resource_name: string;
  date: string;
  day_type: "weekday" | "weekend" | "holiday";
  price_version: number;
  items: QuoteItem[];
  total_amount: number;
};

export type MemberHit = {
  ref: string;
  member_code: string;
  name: string;
  phone_masked: string;
  tier: string | null;
  is_active: boolean;
};

export type ItemAction = "collect" | "uncollectible";

export type Item = {
  kind: "booking" | "ticket";
  code: string;
  version: number;
  source: Source;
  customer: {
    name: string;
    phone_masked: string | null;
    profile_label: string;
    kind: "member" | "temp";
    member_code: string | null;
    tier: string | null;
  };
  schedule: {
    resource_codes: string[];
    resource_names: string[];
    play_date: string;
    start_time: string;
    end_time: string;
    session: { code: string; name: string } | null;
  };
  payment: {
    amount: number;
    payment_status: PaymentStatus;
    payment_method?: PaymentMethod | null;
    paid_at?: string | null;
    collected_by?: string | null;
    uncollectible_reason?: string | null;
    marked_by?: string | null;
    marked_at?: string | null;
  };
  price_breakdown: QuoteItem[];
  note?: string | null;
  created_by: string;
  created_at: string;
  actions: ItemAction[];
};

export type SessionDetail = {
  code: string;
  name: string;
  status: "active" | "deleted";
  play_date: string;
  start_time: string;
  end_time: string;
  resources: { code: string; name: string }[];
  ticket_price: number;
  capacity: number;
  taken: number;
  is_full: boolean;
  created_by: string;
  created_at: string;
  version: number;
  tickets: {
    code: string;
    customer_name: string;
    phone_masked: string | null;
    source: Source;
    payment_status: PaymentStatus;
    amount: number;
    created_at: string;
  }[];
  active_holds: { seats: number; expires_at: string }[];
  can: { register: boolean; delete: boolean };
};

export type SearchResult = { kind: "booking" | "ticket" | "session"; code: string; play_date: string };

export type TransactionRow = {
  kind: "booking" | "ticket";
  code: string;
  play_date: string;
  start_time: string;
  end_time: string;
  resource_codes: string[];
  customer_name: string;
  phone_masked: string | null;
  amount: number;
  payment_status: PaymentStatus;
  payment_method: PaymentMethod | null;
  source: Source;
};

export type Transactions = {
  date_from: string;
  date_to: string;
  rows: TransactionRow[];
  page: number;
  page_size: number;
  total: number;
  cards: Record<PaymentStatus, { amount: number; count: number }>;
};

/** Khách gửi lên: đúng một trong hai (server tự dựng snapshot – ADR-004 S8). */
export type CustomerPayload = { member_code: string } | { temp: { full_name: string; phone: string; note?: string } };

/** Vùng chọn trên lịch. */
export type Selection = { resourceCodes: string[]; date: string; startHour: number; endHour: number };
