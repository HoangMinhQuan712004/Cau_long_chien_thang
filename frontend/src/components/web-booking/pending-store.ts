"use client";

import { useSyncExternalStore } from "react";
import type { components } from "@/lib/api/schema";
import type { Checkout } from "./types";

// Đơn chờ thanh toán của máy này (localStorage): thanh nhắc "Đang giữ chỗ", thẻ "Chờ thanh toán", chặn đặt đơn mới.
// Đồng hồ theo giờ server: lưu `offset` = server_now − giờ máy lúc đọc checkout ⇒ đổi trang / tải lại không đếm lại.

export type PendingOrder = {
  token: string;
  code: string;
  /** "Sân 1" / "Sân 1, Sân 2" / "Vé Giải ABC × 2" */
  title: string;
  /** YYYY-MM-DD */
  date: string;
  /** HH:MM */
  start: string;
  end: string;
  expiresAt: string;
  offset: number;
  /** Đặt trong khu hội viên ⇒ màn QR /hoi-vien/thanh-toan/{token} */
  member: boolean;
  /** Server báo đã hết giờ (đồng hồ máy có thể chưa về 0) */
  expired?: boolean;
  /** Đã trả một phần ⇒ không hủy được */
  locked?: boolean;
  /** Đặt sân: từng sân · giờ (đơn nhiều sân tách dòng); vé: không có */
  slots?: { name: string; start: string; end: string }[];
};

/** Đơn chờ do server trả (409 E-WEB-4 khi tạo đơn mới, GET đơn chờ của hội viên). */
export type PendingCheckout = components["schemas"]["PendingCheckout"];

const KEY = "wk-pending-v1";
const EVENT = "wk-pending";

let cacheRaw: string | null = null;
let cacheValue: PendingOrder | null = null;

function readRaw(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null; // trình duyệt chặn bộ nhớ ⇒ coi như không có đơn chờ
  }
}

export function readPending(): PendingOrder | null {
  const raw = readRaw();
  if (raw === cacheRaw) return cacheValue;
  cacheRaw = raw;
  try {
    cacheValue = raw ? (JSON.parse(raw) as PendingOrder) : null;
  } catch {
    cacheValue = null;
  }
  return cacheValue;
}

function write(value: PendingOrder | null) {
  try {
    if (value) localStorage.setItem(KEY, JSON.stringify(value));
    else localStorage.removeItem(KEY);
  } catch {
    /* không lưu được thì thôi: thanh nhắc chỉ là phụ */
  }
  window.dispatchEvent(new Event(EVENT));
}

export const savePending = (value: PendingOrder) => write(value);

/** Xóa đơn chờ; có `token` thì chỉ xóa khi đúng đơn đó (tránh xóa nhầm đơn mới hơn ở tab khác). */
export function clearPending(token?: string) {
  const cur = readPending();
  if (!cur || (token && cur.token !== token)) return;
  write(null);
}

const hhmm = (t: string) => t.slice(0, 5);

/** Đơn chờ từ checkout đang `pending` (màn QR); checkout khác ⇒ null. */
export function pendingFromCheckout(c: Checkout, token: string, member: boolean): PendingOrder | null {
  if (c.status !== "pending") return null;
  const base = { token, code: c.order_code, expiresAt: c.expires_at, offset: Date.parse(c.server_now) - Date.now(), member };
  if (c.kind === "ticket" && c.event) {
    const e = c.event;
    return { ...base, title: `Vé ${e.name} × ${e.seats}`, date: e.play_date, start: hhmm(e.start_time), end: hhmm(e.end_time) };
  }
  if (!c.items.length) return null;
  const starts = c.items.map((i) => hhmm(i.start_time)).sort();
  const ends = c.items.map((i) => hhmm(i.end_time)).sort();
  const title = [...new Set(c.items.map((i) => i.resource_name))].join(", ");
  const slots = c.items.map((i) => ({ name: i.resource_name, start: hhmm(i.start_time), end: hhmm(i.end_time) }));
  return { ...base, title, date: c.items[0].play_date, start: starts[0], end: ends[ends.length - 1], slots };
}

/** Đơn chờ từ server; không có `pay_token` (đơn rất cũ) ⇒ null vì không dẫn được tới màn QR. */
export function pendingFromApi(pc: PendingCheckout, member: boolean): PendingOrder | null {
  if (!pc.pay_token) return null;
  return {
    token: pc.pay_token,
    code: pc.order_code,
    title: pc.kind === "ticket" ? `Vé ${pc.title}` : pc.title,
    date: pc.play_date,
    start: hhmm(pc.start_time),
    end: hhmm(pc.end_time),
    expiresAt: pc.expires_at,
    offset: Date.parse(pc.server_now) - Date.now(),
    member,
    locked: pc.paid_amount > 0,
    slots: pc.slots?.map((x) => ({ name: x.resource_name, start: hhmm(x.start_time), end: hhmm(x.end_time) })),
  };
}

/** Số giây còn giữ chỗ theo giờ server. */
export const secondsLeft = (p: PendingOrder, now = Date.now()) =>
  Math.max(0, Math.ceil((Date.parse(p.expiresAt) - (now + p.offset)) / 1000));

/** Màn QR của đơn. */
export const payHref = (p: PendingOrder) => `${p.member ? "/hoi-vien" : ""}/thanh-toan/${p.token}`;

/** "Sân 1 · 13:00–15:00" */
export const pendingLabel = (p: PendingOrder) => `${p.title} · ${p.start}–${p.end}`;

function subscribe(onChange: () => void) {
  // `storage`: tab khác đổi; EVENT: tab này đổi
  window.addEventListener("storage", onChange);
  window.addEventListener(EVENT, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(EVENT, onChange);
  };
}

/** Đơn chờ hiện tại (render server ⇒ null). */
export function usePendingOrder(): PendingOrder | null {
  return useSyncExternalStore(subscribe, readPending, () => null);
}
