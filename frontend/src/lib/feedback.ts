import "client-only";
import { useSyncExternalStore } from "react";

// Kho nhỏ dùng chung cho toast và lớp phủ "Mất kết nối" (E-017). Không phụ thuộc thư viện ngoài.

export type ToastKind = "success" | "error" | "info";
export type ToastItem = { id: number; title: string; sub?: string; kind: ToastKind };

const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
};

let toasts: ToastItem[] = [];
let nextId = 1;
let reconnecting = 0;

/** Hiện thông báo góc phải; tự tắt sau vài giây (lỗi lâu hơn). */
export function toast(title: string, sub?: string, kind: ToastKind = "success") {
  const id = nextId++;
  toasts = [...toasts, { id, title, sub, kind }];
  emit();
  setTimeout(() => dismissToast(id), kind === "error" ? 9000 : 6000);
}

export function dismissToast(id: number) {
  if (!toasts.some((t) => t.id === id)) return;
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}

/** Gọi khi một lệnh ghi đang tự thử kết nối lại. Trả về hàm kết thúc. */
export function beginReconnect(): () => void {
  reconnecting += 1;
  emit();
  let done = false;
  return () => {
    if (done) return;
    done = true;
    reconnecting -= 1;
    emit();
  };
}

const EMPTY: ToastItem[] = [];
export const useToasts = () =>
  useSyncExternalStore(
    subscribe,
    () => toasts,
    () => EMPTY,
  );

export const useReconnecting = () =>
  useSyncExternalStore(
    subscribe,
    () => reconnecting > 0,
    () => false,
  );
