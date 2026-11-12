import "client-only";
import { looseApi } from "@/lib/api/client";
import { toApiError, type ApiError } from "@/lib/api/write";
import type {
  Calendar,
  CustomerPayload,
  Item,
  MemberHit,
  MoveTarget,
  PaymentMethod,
  Quote,
  RecurringBody,
  RecurringPreview,
  BookingOrderList,
  CancelPreview,
  CollectQr,
  RecurringOrderList,
  RecurringPreviewBody,
  SearchResult,
  SessionDetail,
  Transactions,
} from "./types";

// Lời gọi API của màn đặt sân. Đọc: trả `Read<T>`; ghi: dùng `write()` (Idempotency-Key) ở nơi gọi, với các hàm `send*` dưới đây.

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

const P = "/api/v1";

export const getCalendar = (date: string) =>
  read<Calendar>(() => looseApi.GET(`${P}/booking/calendar`, { params: { query: { date } } }));

export const searchCode = (code: string) =>
  read<SearchResult>(() => looseApi.GET(`${P}/booking/search`, { params: { query: { code } } }));

export const searchMembers = (q: string) =>
  read<MemberHit[]>(() => looseApi.GET(`${P}/members/search`, { params: { query: { q } } }));

export const getQuote = (resource_code: string, date: string, start_hour: number, end_hour: number) =>
  read<Quote>(() => looseApi.POST(`${P}/booking/quote`, { body: { resource_code, date, start_hour, end_hour } }));

export const getItem = (code: string) =>
  read<Item>(() => looseApi.GET(`${P}/booking/items/{code}`, { params: { path: { code } } }));

export const getSession = (code: string) =>
  read<SessionDetail>(() => looseApi.GET(`${P}/booking/sessions/{code}`, { params: { path: { code } } }));

/** Lọc sổ tiền vào theo ngày nhận / hoàn tiền (giờ VN, ≤ 92 ngày), T-057. */
export type TransactionFilters = {
  from?: string;
  to?: string;
  resource?: string;
  method?: "" | "cash" | "transfer";
  kind?: "" | "in" | "refund";
  q?: string;
  page?: number;
};
export const getTransactions = (f: TransactionFilters) => {
  const query = Object.fromEntries(Object.entries(f).filter(([, v]) => v !== undefined && v !== ""));
  return read<Transactions>(() => looseApi.GET(`${P}/booking/transactions`, { params: { query } }));
};

// ---- Lệnh ghi: truyền vào `write((key) => send...(key, ...))` ----
const idem = (key: string) => ({ "Idempotency-Key": key });

/** Một lần bấm Đặt sân = một đơn gồm 1–20 khối cùng ngày (T-019). Trả `{order_code, bookings[]}`; khối trùng lịch → 409 E-003 + `conflicts`. */
export const sendCounterBooking = (
  key: string,
  v: { date: string; blocks: { resource_code: string; start_hour: number; end_hour: number }[]; customer: CustomerPayload },
) => looseApi.POST(`${P}/front-desk/bookings`, { body: v, headers: idem(key) });

/** QR chuyển khoản cho "Thu cả đơn" (T-058); hỏi lại định kỳ khi popup mở. 409 E-PAY-9 chưa cài nhận tiền, 409 E-BOOK-4 hết khối chưa thu, 404 E-BOOK-3. */
export const getCollectQr = (orderCode: string) =>
  read<CollectQr>(() =>
    looseApi.GET(`${P}/front-desk/orders/{code}/collect-qr`, { params: { path: { code: orderCode } }, cache: "no-store" }),
  );

/** Mọi khối của một đơn (theo mã đơn), như hộp Đơn: tìm mã rồi lấy từng khối. */
export async function getOrderItems(orderCode: string): Promise<Read<Item[]>> {
  const found = await searchCode(orderCode);
  if (!found.ok) return found;
  const codes = found.data.codes?.length ? found.data.codes : [found.data.code];
  const all = await Promise.all(codes.map((c) => getItem(c)));
  const failed = all.find((r) => !r.ok);
  if (failed && !failed.ok) return failed;
  return { ok: true, data: all.flatMap((r) => (r.ok ? [r.data] : [])) };
}

/** Không thu được cả đơn (T-064): chỉ các khối đã tới giờ; khối sau giữ Chưa thanh toán. 422 E-PAY-1, 409 E-BOOK-4, 404 E-BOOK-3. */
export const sendOrderUncollectible = (key: string, orderCode: string, reason: string) =>
  looseApi.POST(`${P}/booking/orders/{order_code}/uncollectible`, {
    params: { path: { order_code: orderCode } },
    body: { reason },
    headers: idem(key),
  });

/** QR chuyển khoản cho MỘT buổi (T-065, nội dung = mã con bỏ gạch); `order_code` trong kết quả là mã con, `blocks` = 1. */
export const getItemCollectQr = (code: string) =>
  read<CollectQr>(() => looseApi.GET(`${P}/front-desk/items/{code}/collect-qr`, { params: { path: { code } }, cache: "no-store" }));

/** Thu tiền mặt mọi khối Chưa thanh toán của đơn. */
export const sendCollectOrder = (key: string, orderCode: string) =>
  looseApi.POST(`${P}/booking/orders/{order_code}/collect`, { params: { path: { order_code: orderCode } }, body: { method: "cash" }, headers: idem(key) });

export const sendCreateSession = (
  key: string,
  v: { resource_codes: string[]; date: string; start_hour: number; end_hour: number; name: string; capacity: number | null; ticket_price: number | null },
) => looseApi.POST(`${P}/booking/sessions`, { body: v, headers: idem(key) });

export const sendDeleteSession = (key: string, code: string, version: number) =>
  looseApi.DELETE(`${P}/booking/sessions/{code}`, { params: { path: { code } }, body: { version }, headers: idem(key) });

/** Đăng ký vé cho nhiều người một lần (T-071): tất cả hoặc không; 409 E-024 "Chỉ còn n chỗ.", 422 E-001 / E-004. 201 `{tickets}`. */
export const sendTicketBatch = (key: string, sessionCode: string, customers: CustomerPayload[]) =>
  looseApi.POST(`${P}/front-desk/sessions/{code}/tickets/batch`, {
    params: { path: { code: sessionCode } },
    body: { customers },
    headers: idem(key),
  });

export const sendCollect = (key: string, code: string, method: Extract<PaymentMethod, "cash" | "transfer">, version: number) =>
  looseApi.POST(`${P}/booking/items/{code}/collect`, { params: { path: { code } }, body: { method, version }, headers: idem(key) });

export const sendUncollectible = (key: string, code: string, reason: string, version: number) =>
  looseApi.POST(`${P}/booking/items/{code}/uncollectible`, {
    params: { path: { code } },
    body: { reason, version },
    headers: idem(key),
  });

// ---- Hủy (T-051, Admin) ----
/** Hủy một booking / vé (T-052: cả buổi đang chơi / đã qua nếu đã thu). Đã thu thì phải gửi `refund_confirmed: true`. Lỗi E-PAY-5/6/7, 409 khi `version` lệch. */
export const sendCancelItem = (key: string, code: string, v: { reason: string; version: number; refund_confirmed: boolean }) =>
  looseApi.POST(`${P}/front-desk/items/{code}/cancel`, { params: { path: { code } }, body: v, headers: idem(key) });

/** Sân trống cùng khung để đổi sân (BE đã lọc). */
export const getMoveTargets = (code: string) =>
  read<MoveTarget[]>(() => looseApi.GET(`${P}/booking/items/{code}/move-targets`, { params: { path: { code } } }));

export const sendMove = (key: string, code: string, v: { resource_code: string; version: number; reason: string }) =>
  looseApi.POST(`${P}/booking/items/{code}/move`, { params: { path: { code } }, body: v, headers: idem(key) });

/** Xem trước hủy cả đơn: buổi sẽ hủy / bị bỏ qua + tổng tiền. */
export const getOrderCancelPreview = (orderCode: string) =>
  read<CancelPreview>(() => looseApi.GET(`${P}/front-desk/orders/{order_code}/cancel-preview`, { params: { path: { order_code: orderCode } } }));

/** Hủy các buổi trong `codes` (lấy từ xem trước); server kiểm lại từng buổi lúc hủy. */
export const sendCancelOrder = (key: string, orderCode: string, v: { reason: string; refund_confirmed: boolean; codes: string[] }) =>
  looseApi.POST(`${P}/front-desk/orders/{order_code}/cancel`, { params: { path: { order_code: orderCode } }, body: v, headers: idem(key) });

// ---- Đặt sân định kỳ (T-035, Admin) ----
/** Xem trước các buổi + tiền (không ghi). Không có buổi nào thì `count = 0`. */
export const getRecurringPreview = (body: RecurringPreviewBody, signal?: AbortSignal) =>
  read<RecurringPreview>(() => looseApi.POST(`${P}/front-desk/recurring/preview`, { body, headers: idem(crypto.randomUUID()), signal }));

/** Đặt cả đợt trong một đơn (tất cả hoặc không). Buổi lỗi → 409 E-BOOK-5 + `conflicts[{date, start, reason}]`. */
export const sendRecurring = (key: string, body: RecurringBody) => looseApi.POST(`${P}/front-desk/recurring`, { body, headers: idem(key) });

// ---- Danh sách đơn định kỳ (T-039, Admin) ----
export const getRecurringOrders = (f: { status?: string; q?: string; page?: number; size?: number }) => {
  const query = Object.fromEntries(Object.entries(f).filter(([, v]) => v !== undefined && v !== ""));
  return read<RecurringOrderList>(() => looseApi.GET(`${P}/front-desk/recurring`, { params: { query } }));
};

// ---- Đơn đặt sân (T-041, Admin): mọi đơn quầy / online / định kỳ, không gồm vé ----
export const getBookingOrders = (f: { kind?: string; status?: string; q?: string; date_from?: string; date_to?: string; page?: number; size?: number }) => {
  const query = Object.fromEntries(Object.entries(f).filter(([, v]) => v !== undefined && v !== ""));
  return read<BookingOrderList>(() => looseApi.GET(`${P}/front-desk/orders`, { params: { query } }));
};
