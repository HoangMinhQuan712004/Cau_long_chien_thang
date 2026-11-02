"use client";

import { useMemo, useSyncExternalStore } from "react";

// Kho nhỏ quanh sessionStorage dùng chung cho luồng đặt sân (booking-flow) và popup mua vé (event-dialog).

// phone_token (30 phút) của SĐT đã xác minh OTP: dùng lại cho các lượt đặt kế tiếp, không bắt nhập mã lại
export const PHONE_TOKEN_KEY = "wk-phone-token-v1";

export type PhoneToken = { phone: string; token: string; expiresAt: string };

export function readJson<T>(key: string): T | null {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}
export function writeJson(key: string, value: unknown) {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* sessionStorage có thể bị chặn (chế độ riêng tư) – bỏ qua, không ảnh hưởng luồng đặt */
  }
}
export function removeKey(key: string) {
  try {
    sessionStorage.removeItem(key);
  } catch {
    /* bỏ qua */
  }
}

/** phone_token còn dùng được (còn > 15 giây) cho đúng SĐT này, không thì null. */
export function savedToken(forPhone: string): string | null {
  const t = readJson<PhoneToken>(PHONE_TOKEN_KEY);
  return t && t.phone === forPhone && Date.parse(t.expiresAt) - Date.now() > 15_000 ? t.token : null;
}

// Nhãn "đã xác minh" cập nhật khi lưu / xóa token (không setState trong effect)
const tokenListeners = new Set<() => void>();
const subscribeToken = (cb: () => void) => {
  tokenListeners.add(cb);
  return () => void tokenListeners.delete(cb);
};
export const notifyToken = () => tokenListeners.forEach((l) => l());
const readTokenRaw = (): string | null => {
  try {
    return sessionStorage.getItem(PHONE_TOKEN_KEY);
  } catch {
    return null;
  }
};

/** Lưu token sau khi xác minh OTP và báo cho mọi nơi đang đọc. */
export function saveToken(value: PhoneToken) {
  writeJson(PHONE_TOKEN_KEY, value);
  notifyToken();
}
/** Xóa token (hết hạn / không khớp SĐT) ⇒ xác minh lại ở lần bấm kế tiếp. */
export function clearToken() {
  removeKey(PHONE_TOKEN_KEY);
  notifyToken();
}

/** SĐT đã có phone_token (chỉ để đổi nhãn nút / hiện "đã xác minh"); hạn thật được kiểm lại lúc bấm nút. */
export function useVerifiedPhone(): string | null {
  const raw = useSyncExternalStore(subscribeToken, readTokenRaw, () => null);
  return useMemo(() => {
    try {
      return raw ? (JSON.parse(raw) as PhoneToken).phone : null;
    } catch {
      return null;
    }
  }, [raw]);
}
