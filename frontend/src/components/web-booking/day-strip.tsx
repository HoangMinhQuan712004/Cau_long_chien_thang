"use client";

import { useId } from "react";
import { cn } from "@/lib/cn";
import { addDaysIso } from "@/lib/format";

// Dải 7 ngày của màn Đặt sân (T-028 AC4): "Hôm nay", T2…CN (T7/CN màu vàng nhạt), ‹ › chuyển tuần, "Tháng ▾" chọn tháng.
// Chỉ là bộ chọn ngày: đổi ngày do cha xử lý (tải lưới tại chỗ, hỏi nếu đang có ô chọn).

const DOW = ["CN", "T2", "T3", "T4", "T5", "T6", "T7"];
const MONTHS = 12;
const dow = (d: string) => new Date(`${d}T00:00:00Z`).getUTCDay();
const monthOf = (d: string) => d.slice(0, 7);
const monthLabel = (m: string) => `Tháng ${Number(m.slice(5, 7))}, ${m.slice(0, 4)}`;

type Props = { date: string; today: string; onPick: (date: string) => void };

/** Số ngày từ `from` đến `to` (cả hai dạng YYYY-MM-DD). */
const daysBetween = (from: string, to: string) => Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 864e5);

export function DayStrip({ date, today, onPick }: Props) {
  const monthId = useId();
  // Dải = 7 ngày, trang đầu bắt đầu từ "Hôm nay"; ngày đang chọn quyết định trang nào được hiện
  const start = addDaysIso(today, Math.max(0, Math.floor(daysBetween(today, date) / 7)) * 7);
  const days = Array.from({ length: 7 }, (_, i) => addDaysIso(start, i));

  const months = Array.from({ length: MONTHS }, (_, i) => {
    const d = new Date(Date.UTC(Number(today.slice(0, 4)), Number(today.slice(5, 7)) - 1 + i, 1));
    return d.toISOString().slice(0, 7);
  });

  // Chuyển tuần: giữ cùng vị trí trong tuần (cùng thứ), không lùi quá hôm nay
  function shift(weeks: number) {
    const next = addDaysIso(date, weeks * 7);
    onPick(next < today ? today : next);
  }

  function pickMonth(m: string) {
    const first = `${m}-01`;
    onPick(first < today ? today : first);
  }

  const atStart = start <= today;

  return (
    <div className="rounded-2xl bg-appbar p-3 text-surface sm:p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="relative">
          <label htmlFor={monthId} className="sr-only">
            Chọn tháng
          </label>
          <select
            id={monthId}
            value={monthOf(date)}
            onChange={(e) => pickMonth(e.target.value)}
            className="h-11 appearance-none rounded-lg border border-surface/25 bg-surface/10 py-0 pr-9 pl-3 text-sm font-bold text-surface focus-ring"
          >
            {months.map((m) => (
              <option key={m} value={m} className="text-foreground">
                {monthLabel(m)}
              </option>
            ))}
          </select>
          <span aria-hidden className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-xs">
            ▾
          </span>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            aria-label="Tuần trước"
            disabled={atStart}
            onClick={() => shift(-1)}
            className="grid size-11 place-items-center rounded-lg border border-surface/25 bg-surface/10 text-lg hover:bg-surface/20 focus-ring disabled:opacity-35 disabled:hover:bg-surface/10"
          >
            <span aria-hidden>‹</span>
          </button>
          <button
            type="button"
            aria-label="Tuần sau"
            onClick={() => shift(1)}
            className="grid size-11 place-items-center rounded-lg border border-surface/25 bg-surface/10 text-lg hover:bg-surface/20 focus-ring"
          >
            <span aria-hidden>›</span>
          </button>
        </div>
      </div>

      <div role="group" aria-label="Chọn ngày" className="mt-3 grid grid-cols-7 gap-1.5 sm:gap-2">
        {days.map((d) => {
          const on = d === date;
          const past = d < today;
          const weekend = dow(d) === 0 || dow(d) === 6;
          const label = d === today ? "Hôm nay" : DOW[dow(d)];
          return (
            <button
              key={d}
              type="button"
              disabled={past}
              aria-pressed={on}
              aria-label={`${label}, ${d.slice(8, 10)}/${d.slice(5, 7)}/${d.slice(0, 4)}`}
              onClick={() => !on && onPick(d)}
              className={cn(
                "flex min-h-14 min-w-0 flex-col items-center justify-center rounded-lg border px-0.5 text-center leading-tight focus-ring",
                on ? "border-surface bg-surface text-primary-hover shadow-card" : "border-surface/25 text-surface hover:bg-surface/12",
                past && "opacity-35 hover:bg-transparent",
              )}
            >
              <span className={cn("text-[11px] font-semibold sm:text-xs", !on && weekend && "text-accent-soft", d === today && "text-[10px] tracking-tight whitespace-nowrap sm:text-xs")}>{label}</span>
              <span className="text-[13px] font-bold tabular-nums sm:text-sm">
                {d.slice(8, 10)}/{d.slice(5, 7)}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
