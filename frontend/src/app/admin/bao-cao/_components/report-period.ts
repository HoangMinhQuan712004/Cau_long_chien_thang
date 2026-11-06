import { addDaysIso, todayVn } from "@/lib/format";

export type PeriodMode = "week" | "month" | "custom";
export type Period = { mode: PeriodMode; from: string; to: string };

/** Kỳ tối đa (BR-004, OQ-3). */
export const MAX_DAYS = 90;
const PRESET_DAYS = { week: 7, month: 30 } as const;

/** Số ngày của khoảng, tính cả 2 đầu. */
export const daysOf = (from: string, to: string) =>
  Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000) + 1;

/** Tuần = 7 ngày, Tháng = 30 ngày, lùi từ hôm nay, gồm cả hôm nay (BR-003). */
export function presetPeriod(mode: "week" | "month", today = todayVn()): Period {
  return { mode, from: addDaysIso(today, 1 - PRESET_DAYS[mode]), to: today };
}

/** Lỗi khoảng ngày (BR-004): E-002 từ > đến, E-003 dài hơn 90 ngày. */
export type RangeError = "fromAfterTo" | "tooLong";

export function rangeError(from: string, to: string): RangeError | null {
  if (from > to) return "fromAfterTo";
  if (daysOf(from, to) > MAX_DAYS) return "tooLong";
  return null;
}
