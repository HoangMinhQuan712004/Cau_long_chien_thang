// Hằng số + hàm ngày giờ dùng chung của hộp Đặt sân định kỳ (tách từ recurring-dialog.tsx).

import { formatDayMonth, weekdayIndex } from "@/lib/format";
import type { RecurringSuggestion } from "./types";

export const DOW = [
  [1, "T2"],
  [2, "T3"],
  [3, "T4"],
  [4, "T5"],
  [5, "T6"],
  [6, "T7"],
  [7, "CN"],
] as const;
/** Thứ ISO (1 = T2) của một ngày YYYY-MM-DD. */
export const isoDow = (d: string) => weekdayIndex(d) + 1;
export const dowName = (d: string) => DOW.find(([n]) => n === isoDow(d))?.[1] ?? "";
export const pad = (n: number) => String(n).padStart(2, "0");
export const MAX_DAYS = 92;
export const DEBOUNCE_MS = 400;

/** Chỉnh sửa của một buổi so với lịch chung. */
export type Tweak = { resource_code?: string; start_hour?: number; end_hour?: number; removed?: boolean };

const REASON: Record<string, string> = {
  booked: "Đã có người đặt",
  event: "Trùng sự kiện",
  hold: "Đang giữ chỗ online",
  closed: "Ngoài giờ mở cửa",
  inactive: "Sân ngừng hoạt động",
  past: "Giờ đã qua",
  no_price: "Chưa có bảng giá",
};
export const reasonText = (r?: string | null) => (r ? (REASON[r] ?? r) : "");


/** Lựa chọn giờ cho Dropdown: giờ bắt đầu theo cột lịch; giờ kết thúc = cột + 1. */
export const hourOptions = (columns: number[], end = false) => columns.map((h) => ({ value: String(end ? h + 1 : h), label: `${pad(end ? h + 1 : h)}:00` }));

/** Nhãn kiểu gợi ý của BE (T-043, như dev). */
export const KIND_LABEL: Record<RecurringSuggestion["kind"], string> = { shift: "Lệch giờ", court: "Sân khác" };

/** "12 buổi · S01 · T3, T5, T7 · 10/11 → 28/11" (dòng dưới "Tổng thanh toán"). */
export function orderSummary(items: { date: string; resource_code: string }[], weekdays: number[]) {
  if (!items.length) return "";
  const dates = items.map((i) => i.date).sort();
  const courts = [...new Set(items.map((i) => i.resource_code))].join(", ");
  const dows = DOW.filter(([n]) => weekdays.includes(n)).map(([, l]) => l).join(", ");
  return [`${items.length} buổi`, courts, dows, `${formatDayMonth(dates[0])} → ${formatDayMonth(dates[dates.length - 1])}`].filter(Boolean).join(" · ");
}
