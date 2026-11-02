import type { components } from "@/lib/api/schema";

// Kiểu dữ liệu của web khách (T-008): lấy thẳng từ `schema.d.ts` (sinh từ backend) nên backend đổi hình dạng thì `tsc` báo lỗi ở chỗ dùng.
type S = components["schemas"];

export type WebCalendar = S["WebCalendarOut"];
export type WebResource = S["PublicCalendarResource"];
export type WebSlot = S["PublicSlot"];
export type SlotState = WebSlot["state"];
export type Bank = S["BankInfo"];
export type CheckoutItem = S["WebCheckoutItem"];
/** Response tạo checkout (có `token`, chỉ trả ở lần tạo). */
export type CheckoutCreated = S["CheckoutCreatedOut"];
export type Checkout = S["CheckoutOut"];
export type Lookup = S["LookupOut"];
export type LookupStatus = Lookup["status"];

/** Ô đã chọn trên lưới: sân + giờ bắt đầu. */
export type Cell = { code: string; hour: number };

export const MAX_CELLS = 16;

/** Khóa sessionStorage do màn "Hết thời gian giữ chỗ" ghi để "Đặt lại" chọn sẵn các ô cũ nếu còn trống: `{date, items:[{code,hour}]}`. */
export const RESTORE_KEY = "wk-restore-v1";

// ---- Vé sự kiện (T-023): kiểu viết tay theo spec cho tới khi merge `be/T-023-ve-online` ----

export type PayStatus = "unpaid" | "paid" | "uncollectible";

/** Ô lịch có thêm các trường riêng của hội viên (chỉ có ở `/member-area/booking-calendar`) và `event_code` (cả lịch công khai). */
export type SlotExtra = { mine?: boolean; order_code?: string | null; event_code?: string | null; has_ticket?: boolean };

export type EventReason = "started" | "full" | "free" | "online_off" | "deleted";

export type EventDetail = {
  code: string;
  name: string;
  play_date: string;
  start_time: string;
  end_time: string;
  resource_names: string[];
  ticket_price: number;
  capacity: number;
  taken: number;
  can_buy: boolean;
  reason: EventReason | null;
  /** Chỉ có khi gọi với cookie hội viên liên kết */
  my_tickets?: { code: string; pay_status: PayStatus }[];
};

export type EventCheckoutBody = {
  event_code: string;
  seats: number;
  full_name: string;
  phone: string;
  phone_token?: string;
  as_member?: boolean;
};

/** Khối `event` của CheckoutOut (kind='ticket') */
export type TicketInfo = { name: string; play_date: string; start_time: string; end_time: string; seats: number; ticket_codes?: string[] };
