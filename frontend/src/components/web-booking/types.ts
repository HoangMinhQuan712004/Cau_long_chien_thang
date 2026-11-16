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

// ---- Vé sự kiện (T-023) ----

export type PayStatus = "unpaid" | "paid" | "uncollectible" | "cancelled";
export type MemberCalendar = S["MemberCalendarOut"];
/** Trường riêng của ô lịch hội viên + `event_code` (lịch công khai cũng có) */
export type SlotExtra = Partial<Pick<S["MemberSlot"], "mine" | "holding" | "order_code" | "has_ticket" | "event_code">>;
export type EventDetail = S["WebEventOut"];
export type EventReason = NonNullable<EventDetail["reason"]>;
export type EventCheckoutBody = S["EventCheckoutIn"];
/** Khối `event` của CheckoutOut (kind='ticket') */
export type TicketInfo = S["CheckoutEvent"];

/** Chỗ trống cuối banner màn Đặt sân để bước 1 đưa bộ chọn ngày vào (step1-layouts.tsx). */
export const BOOKING_BANNER_SLOT = "booking-banner-slot";
