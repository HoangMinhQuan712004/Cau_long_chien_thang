"use client";

import { useMemo, useSyncExternalStore } from "react";

// T-075: "lượt đang chờ thanh toán" của trình duyệt này (localStorage, sống qua đóng tab).
// Token đã nằm sẵn trên URL trang thanh toán ⇒ lưu ở đây không lộ thêm gì. Mỗi khu một lượt (khách / hội viên tách riêng,
// lượt mới ghi đè lượt cũ). Dùng để: hiện banner "Tiếp tục thanh toán", đánh dấu ô "Chờ bạn thanh toán" trên lịch,
// và quay lại đúng trang QR mà không tạo lượt mới.

/** Ân hạn nhận tiền báo trễ sau hạn giữ chỗ (khung vẫn chiếm chỗ trong lúc này). */
export const GRACE_MS = 60_000;

export type PendingItem = { resource_code: string; play_date: string; start_hour: number; hours: number };

export type PendingCheckout = {
  token: string;
  kind: "court" | "event";
  member: boolean;
  order_code: string;
  /** Hạn thanh toán (giờ server, chưa cộng ân hạn). */
  expires_at: string;
  /** Giờ server lúc nhận `expires_at` + giờ máy lúc đó ⇒ bù lệch đồng hồ máy khách. */
  server_now: string;
  client_at: number;
  items?: PendingItem[];
  event_code?: string;
  /** "Sân 4 · 15:00–17:00" / "Vé Giải ABC × 2 · 18:00–20:00" – thẻ nhắc lấy từ server rồi ghi lại */
  label?: string;
};

const keyOf = (member: boolean) => (member ? "ck-pending-member-v1" : "ck-pending-web-v1");

const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());
function subscribe(cb: () => void) {
  listeners.add(cb);
  // Tab khác ghi / xóa (vd vừa thanh toán xong ở tab kia) ⇒ cập nhật tab này
  const onStorage = (e: StorageEvent) => {
    if (!e.key || e.key.startsWith("ck-pending-")) cb();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", onStorage);
  };
}

function readRaw(member: boolean): string | null {
  try {
    return localStorage.getItem(keyOf(member));
  } catch {
    return null; // localStorage bị chặn (chế độ riêng tư) ⇒ coi như không có lượt nào
  }
}

/** Giờ server ước tính theo lượt đã lưu. */
export const serverNowOf = (p: PendingCheckout) => Date.now() + (Date.parse(p.server_now) - p.client_at);

/** Đã quá hạn + ân hạn theo đồng hồ cục bộ (đã bù lệch) ⇒ chắc chắn không còn dùng được. */
export const isStale = (p: PendingCheckout) => serverNowOf(p) > Date.parse(p.expires_at) + GRACE_MS;

function parse(raw: string | null): PendingCheckout | null {
  if (!raw) return null;
  try {
    const p = JSON.parse(raw) as PendingCheckout;
    return p && typeof p.token === "string" && typeof p.expires_at === "string" ? p : null;
  } catch {
    return null;
  }
}

/** Lượt đang chờ của khu này (null khi không có / đã quá hạn + ân hạn). Không tự xóa: nơi gọi xóa khi chắc chắn. */
export function readPending(member: boolean): PendingCheckout | null {
  const p = parse(readRaw(member));
  return p && !isStale(p) ? p : null;
}

/** Lưu ngay sau khi tạo checkout (đặt sân hoặc mua vé) và khi trang thanh toán đọc được hạn mới từ server. */
export function savePending(p: Omit<PendingCheckout, "client_at">) {
  try {
    localStorage.setItem(keyOf(p.member), JSON.stringify({ ...p, client_at: Date.now() } satisfies PendingCheckout));
  } catch {
    /* không lưu được thì chỉ mất banner quay lại; luồng thanh toán không ảnh hưởng */
  }
  notify();
}

type CreatedLike = {
  token: string;
  kind: "court" | "ticket";
  order_code: string;
  expires_at: string;
  server_now: string;
  items: { resource_code: string; play_date: string; start_hour: number; hours: number }[];
  event: { code: string } | null;
};

/** Lưu lượt vừa tạo (response tạo checkout: đặt sân hoặc mua vé) – gọi ngay trước khi chuyển sang trang QR. */
export function rememberCreated(c: CreatedLike, member: boolean) {
  savePending({
    token: c.token,
    kind: c.kind === "ticket" ? "event" : "court",
    member,
    order_code: c.order_code,
    expires_at: c.expires_at,
    server_now: c.server_now,
    ...(c.kind === "ticket"
      ? { event_code: c.event?.code }
      : { items: c.items.map(({ resource_code, play_date, start_hour, hours }) => ({ resource_code, play_date, start_hour, hours })) }),
  });
}

/** Xóa lượt của khu này; `token` có ⇒ chỉ xóa khi đúng lượt đó (không xóa nhầm lượt mới hơn của tab khác). */
export function clearPending(member: boolean, token?: string) {
  try {
    if (token) {
      const cur = parse(readRaw(member));
      if (cur && cur.token !== token) return;
    }
    localStorage.removeItem(keyOf(member));
  } catch {
    /* bỏ qua */
  }
  notify();
}

/** Đường dẫn trang QR của lượt. */
export const paymentPath = (p: Pick<PendingCheckout, "token" | "member">) => (p.member ? `/hoi-vien/thanh-toan/${p.token}` : `/thanh-toan/${p.token}`);

/** Lượt đang chờ (theo dõi thay đổi). `null` ở lần render trên server / trước hydrate. */
export function usePending(member: boolean): PendingCheckout | null {
  const raw = useSyncExternalStore(subscribe, () => readRaw(member), () => null);
  // Cùng chuỗi lưu ⇒ cùng object (dùng được làm dependency); quá hạn + ân hạn thì nơi hiển thị tự ẩn theo đồng hồ
  return useMemo(() => parse(raw), [raw]);
}

/** Ô (sân, ngày, giờ) có thuộc lượt đang chờ không. */
export function ownsCell(p: PendingCheckout | null, date: string, code: string, hour: number): boolean {
  if (!p?.items) return false;
  return p.items.some((it) => it.play_date === date && it.resource_code === code && hour >= it.start_hour && hour < it.start_hour + it.hours);
}
