"use client";

import { Button } from "@/components/ui/button";
import { DateRange, type DateRangeKey, type DateRangeValue } from "@/components/ui/date-range";
import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";
import type { Period } from "./report-period";
import type { ReportError } from "./use-report";

type Props = {
  /** Kỳ đang áp (khoảng ngày sai thì vẫn là kỳ cũ). */
  period: Period;
  /** Hôm nay (YYYY-MM-DD): lịch làm mờ ngày sau hôm nay. */
  today: string;
  /** Lỗi khoảng ngày đang báo (E-002, E-003…), ô `invalid` viền đỏ. */
  error: Exclude<ReportError, "load"> | null;
  invalid: DateRangeKey | null;
  onPreset: (mode: "week" | "month") => void;
  onRange: (range: DateRangeValue, key: DateRangeKey) => void;
  t: Dictionary["report"];
};

const PRESETS = ["week", "month"] as const;

/** Bộ lọc kỳ cho cả màn: nút Tuần / Tháng, Từ ngày – Đến ngày (chọn xong là tính lại), dòng lỗi nếu có. */
export function PeriodFilter({ period, today, error, invalid, onPreset, onRange, t }: Props) {
  const p = t.period;

  return (
    <section aria-label={p.label} className="flex flex-col gap-2">
      <div className={cn(`
        flex flex-col gap-2.5
        sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-5 sm:gap-y-3
      `)}>
        <div className="flex items-center sm:gap-3">
          {/* Điện thoại: bỏ nhãn "Kỳ" đứng lẻ (nhóm nút đã có aria-label), nhóm nút rộng hết hàng */}
          <span className="sr-only text-ui text-muted sm:not-sr-only">{p.label}</span>
          {/* Nhóm nút liền (segmented): đang chọn nền xanh, còn lại nút nhẹ; tự chọn ngày ⇒ cả 2 bỏ chọn */}
          <div role="group" aria-label={p.label} className={cn(`
            flex flex-1 gap-0.5 rounded-lg border border-border-strong bg-surface p-0.5
            sm:flex-none
          `)}>
            {PRESETS.map((mode) => (
              // Bấm nút đang chọn: không làm gì (trừ khi đang báo lỗi ngày ⇒ điền lại ô theo kỳ)
              <Button
                key={mode}
                variant={period.mode === mode ? "primary" : "ghost"}
                aria-pressed={period.mode === mode}
                onClick={() => onPreset(mode)}
                className="min-w-14 flex-1 sm:flex-none"
              >
                {p[mode]}
              </Button>
            ))}
          </div>
        </div>
        <DateRange
          from={period.from}
          to={period.to}
          max={today}
          linked={false}
          // Hàng lọc Báo cáo dư chỗ: giữ ô rộng 160px (ngày không sát icon lịch)
          inputWidth="sm:w-40"
          invalid={invalid}
          onChange={onRange}
          t={p}
        />
      </div>
      {error ? (
        <p role="alert" className="text-xs text-danger sm:text-ui">
          {t.errors[error]}
        </p>
      ) : null}
    </section>
  );
}
