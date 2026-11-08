// Kiểu dữ liệu của booking engine (T-006 §4). Phản chiếu DTO backend `booking_engine/dto.py`.
// TODO(T-006): khi BACKEND handoff và `schema.d.ts` có các kiểu này, đổi sang `components["schemas"][...]`.

// T-051: thêm `cancelled` (Đã hủy, trạng thái cuối). Các trường mới để tùy chọn cho tới khi schema.d.ts có đủ (BE T-051).
export type PaymentStatus = "unpaid" | "paid" | "uncollectible" | "cancelled";
export type PaymentMethod = "cash" | "transfer" | "online_transfer";
export type Source = "counter" | "online";

export type CalendarResource = {
  code: string;
  name: string;
  type: string;
  is_active: boolean;
  /** Giờ bắt đầu các ô Xám (không bán) của sân này. */
  off_hours: number[];
  /** Giá/giờ từng ô bán được (giờ bắt đầu → VND), chỉ để xem trước tổng tiền (T-025 AC9). */
  hour_prices?: Record<string, number>;
};

export type CalendarBlock = {
  type: "booking" | "session" | "hold";
  /** Mã khối (mã con) – dùng để mở chi tiết. */
  code: string | null;
  /** Mã đơn – hiện trên khối (T-019). */
  order_code?: string | null;
  resource_codes: string[];
  start_time: string;
  end_time: string;
  start_hour: number;
  end_hour: number;
  payment_status?: PaymentStatus | null;
  customer_name?: string | null;
  phone?: string | null;
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
  phone: string;
  tier: string | null;
  is_active: boolean;
};

/** Kết quả đặt quầy: một đơn nhiều khối. */
export type CounterOrder = { order_code: string; bookings: Item[] };
/** Kết quả thu cả đơn. */
export type OrderCollect = { order_code: string; collected: string[]; amount: number; bookings: Item[] };

export type ItemAction = "collect" | "uncollectible" | "cancel";

export type Item = {
  kind: "booking" | "ticket";
  /** Mã khối (mã con) với booking. */
  code: string;
  /** Mã đơn; vé thì null. */
  order_code?: string | null;
  version: number;
  source: Source;
  customer: {
    name: string;
    phone: string | null;
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
    session?: { code: string; name: string } | null;
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
    /** T-051: chỉ có khi payment_status = cancelled. Hội viên không thấy lý do. */
    cancel_reason?: string | null;
    cancelled_at?: string | null;
    cancelled_by_label?: string | null;
    /** Số tiền Admin ghi nhận đã hoàn tay (0 nếu khoản chưa thu). */
    refund_amount?: number;
  };
  price_breakdown?: QuoteItem[];
  note?: string | null;
  created_by: string;
  created_at: string;
  actions: ItemAction[];
  /** T-052: giai đoạn của buổi khi hủy (server tính): trước giờ / đang chơi / đã qua; null = không hủy được. */
  cancel_phase?: Api["schemas"]["ItemOut"]["cancel_phase"];
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
    phone: string | null;
    source: Source;
    payment_status: PaymentStatus;
    amount: number;
    created_at: string;
  }[];
  active_holds: { seats: number; expires_at: string }[];
  can: { register: boolean; delete: boolean };
};

/** `kind: "order"` = nhập mã đơn → `codes` là các mã khối của đơn. */
export type SearchResult = {
  kind: "order" | "booking" | "ticket" | "session";
  code: string;
  play_date: string;
  order_code?: string | null;
  codes?: string[];
};

// ---- Lịch sử giao dịch = sổ tiền vào (T-057, ADR-014): mỗi dòng một lần nhận tiền / một lần hoàn ----
export type TransactionEntryItem = {
  code: string;
  kind: "booking" | "ticket";
  resource_name: string;
  play_date: string;
  start_at: string;
  end_at: string;
  amount: number;
};

/** Không có id nội bộ (T-057, SEC4 của QA): FE lấy vị trí dòng trong trang làm key. */
export type TransactionEntry = {
  kind: "in" | "refund";
  /** `transfer` gồm cả tiền SePay của khách đặt online. */
  method: "cash" | "transfer";
  source: "counter" | "counter_qr" | "online";
  /** Luôn dương; dòng hoàn hiện "−". */
  amount: number;
  occurred_at: string;
  /** Mã đơn booking; vé là mã sự kiện. */
  order_code: string | null;
  customer_name: string;
  customer_phone_masked: string | null;
  member_code?: string | null;
  /** "Hệ thống" cho tiền SePay. */
  actor_label: string;
  items: TransactionEntryItem[];
};

export type Transactions = {
  /** VND theo cả bộ lọc (không chỉ trang này): net = cash + transfer − refund. */
  cards: { net: number; cash: number; transfer: number; refund: number };
  items: TransactionEntry[];
  total: number;
  page: number;
  size: number;
};

// ---- Thu cả đơn bằng QR (T-058); SchemaContract bên dưới kiểm khớp CollectQrOut ----
export type CollectQr = {
  order_code: string;
  /** Nội dung chuyển khoản = mã đơn bỏ gạch ("BK20261106001"). */
  pay_ref: string;
  /** Tổng các khối chưa thu lúc hỏi; 0 khi đã thu hết. */
  amount: number;
  status: "unpaid" | "paid";
  blocks: number;
  bank: import("@/components/web-booking/types").Bank;
};

/** Khách gửi lên: đúng một trong hai (server tự dựng snapshot – ADR-004 S8). */
export type CustomerPayload = { member_code: string } | { temp: { full_name: string; phone: string; note?: string } };

/** Vùng chọn trên lịch. */
export type Selection = { resourceCodes: string[]; date: string; startHour: number; endHour: number };

// ---- Kiểm tra lúc biên dịch: kiểu viết tay ở trên phải nhận được response theo `schema.d.ts` (sinh từ backend). ----
// Backend đổi hình dạng response → `tsc` / `npm run build` báo lỗi ở đây thay vì lỗi lúc chạy.
import type { components as Api } from "@/lib/api/schema";

type Accepts<Actual extends Expected, Expected> = [Actual, Expected];
export type SchemaContract = [
  Accepts<Api["schemas"]["CalendarOut"], Calendar>,
  Accepts<Api["schemas"]["QuoteOut"], Quote>,
  Accepts<Api["schemas"]["MemberSearchItem"], MemberHit>,
  Accepts<Api["schemas"]["ItemOut"], Item>,
  Accepts<Api["schemas"]["SessionOut"], SessionDetail>,
  Accepts<Api["schemas"]["SearchResult"], SearchResult>,
  Accepts<Api["schemas"]["TransactionsOut"], Transactions>,
  Accepts<Api["schemas"]["CollectQrOut"], CollectQr>,
];

// ---- Hủy (T-051, Admin): hợp đồng theo spec, thay bằng kiểu sinh khi BE handoff ----
export type CancelSkipReason = "started" | "played" | "cancelled" | "uncollectible";
export type CancelPreview = {
  cancellable: { code: string; play_date: string; start_at: string; resource_name: string; amount: number; payment_status: PaymentStatus }[];
  skipped: { code: string; reason: CancelSkipReason }[];
  refund_total: number;
  unpaid_total: number;
};
export type CancelResult = { cancelled: string[]; skipped: { code: string; reason: CancelSkipReason }[]; refund_total: number };

// ---- Đặt sân định kỳ (T-035, Admin): kiểu sinh từ schema.d.ts ----
/** Một buổi tường minh gửi lên (T-043): FE sinh từ lịch chung rồi áp chỉnh sửa / bỏ buổi. */
export type RecurringSessionIn = Api["schemas"]["RecurringSessionIn"];
/** Gợi ý cho buổi lỗi (T-043 AC1): `shift` = cùng sân lệch giờ, `court` = cùng giờ sân khác. Giá là giá gốc. */
export type RecurringSuggestion = Api["schemas"]["RecurringSuggestion"];
export type RecurringBody = Api["schemas"]["RecurringBookingIn"];
export type RecurringPreviewBody = Api["schemas"]["RecurringPreviewIn"];
export type RecurringSession = Api["schemas"]["RecurringSession"];
export type RecurringPreview = Api["schemas"]["RecurringPreview"];
export type RecurringResult = Api["schemas"]["RecurringCreated"];
/** Buổi không đặt được trong lỗi 409 E-BOOK-5 (`extra.conflicts`). */
export type RecurringConflict = { date: string; start: string; resource_code?: string; reason: string | null; reason_text?: string | null };

// ---- Danh sách đơn định kỳ (T-039): kiểu sinh từ schema.d.ts ----
export type RecurringOrderStatus = Api["schemas"]["RecurringOrderOut"]["status"];
export type RecurringOrderRow = Api["schemas"]["RecurringOrderOut"];
export type RecurringOrderList = Api["schemas"]["RecurringOrderListOut"];

// ---- Đơn đặt sân (T-041): kiểu sinh từ schema.d.ts ----
export type BookingOrderRow = Api["schemas"]["OrderOut"];
export type BookingOrderList = Api["schemas"]["OrderListOut"];
export type BookingOrderKind = BookingOrderRow["kind"];
export type BookingOrderStatus = BookingOrderRow["status"];
