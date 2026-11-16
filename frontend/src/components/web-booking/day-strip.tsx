"use client";

import { cn } from "@/lib/cn";
import { addDaysIso } from "@/lib/format";
import { DatePicker } from "./date-picker";

// Dải 7 ngày của màn Đặt sân (T-028 AC4): "Hôm nay", T2…CN (T7/CN chữ vàng, ngày đang chọn viền + chữ vàng), ‹ › chuyển tuần, nút ngày mở lịch tháng.
// Chỉ là bộ chọn ngày: đổi ngày do cha xử lý (tải lưới tại chỗ, hỏi nếu đang có ô chọn).

const DOW = ["CN", "T2", "T3", "T4", "T5", "T6", "T7"];
const MONTHS = 12;
const dow = (d: string) => new Date(`${d}T00:00:00Z`).getUTCDay();

/** `flat`: bỏ nền thẻ xanh riêng – đặt thẳng lên dải xanh nối banner (màn Đặt sân đang thử bố cục, 12/11). */
type Props = { date: string; today: string; onPick: (date: string) => void; flat?: boolean };

/** Số ngày từ `from` đến `to` (cả hai dạng YYYY-MM-DD). */
const daysBetween = (from: string, to: string) => Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 864e5);

export function DayStrip({ date, today, onPick, flat = false }: Props) {
  // Dải = 7 ngày, trang đầu bắt đầu từ "Hôm nay"; ngày đang chọn quyết định trang nào được hiện
  const start = addDaysIso(today, Math.max(0, Math.floor(daysBetween(today, date) / 7)) * 7);
  const days = Array.from({ length: 7 }, (_, i) => addDaysIso(start, i));

  // Chuyển tuần: giữ cùng vị trí trong tuần (cùng thứ), không lùi quá hôm nay
  function shift(weeks: number) {
    const next = addDaysIso(date, weeks * 7);
    onPick(next < today ? today : next);
  }

  const atStart = start <= today;

  return (
    // Điện thoại: chữ / ô nhỏ hơn (người dùng 03/11); từ sm giữ cỡ cũ
    <div className={cn("text-surface", !flat && "rounded-2xl bg-appbar p-2.5 sm:p-4")}>
      <div className="flex items-center justify-between gap-3">
        {/* Bấm ⇒ lịch tháng bật ra để chọn ngày bất kỳ (thay ô chọn tháng – người dùng 12/11, kiểu Alobo) */}
        <DatePicker date={date} today={today} months={MONTHS} onPick={onPick} />
        <div className="flex gap-2">
          <button
            type="button"
            aria-label="Tuần trước"
            disabled={atStart}
            onClick={() => shift(-1)}
            className="grid size-10 place-items-center sm:size-11 rounded-lg border border-surface/25 bg-surface/10 text-lg hover:bg-surface/20 focus-ring disabled:opacity-35 disabled:hover:bg-surface/10"
          >
            <span aria-hidden>‹</span>
          </button>
          <button
            type="button"
            aria-label="Tuần sau"
            onClick={() => shift(1)}
            className="grid size-10 place-items-center sm:size-11 rounded-lg border border-surface/25 bg-surface/10 text-lg hover:bg-surface/20 focus-ring"
          >
            <span aria-hidden>›</span>
          </button>
        </div>
      </div>

      <div role="group" aria-label="Chọn ngày" className="mt-2.5 grid grid-cols-7 gap-1 sm:mt-3 sm:gap-2">
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
                "flex min-h-11 min-w-0 flex-col items-center justify-center rounded-lg border px-0.5 text-center leading-tight focus-ring sm:min-h-14",
                on ? "border-cta bg-surface/10 text-cta" : "border-surface/25 text-surface hover:bg-surface/12",
                past && "opacity-35 hover:bg-transparent",
              )}
            >
              <span className={cn("text-[10px] font-semibold sm:text-xs", !on && weekend && "text-cta", d === today && "text-[9px] tracking-tight whitespace-nowrap sm:text-xs")}>{label}</span>
              <span className="text-[11px] font-bold tabular-nums sm:text-sm">
                {d.slice(8, 10)}/{d.slice(5, 7)}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
