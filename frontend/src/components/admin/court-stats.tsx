"use client";

import { useEffect, useState } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/cn";
import { formatDayMonthYear, formatNumber, formatVnd } from "@/lib/format";
import { SECTION, SECTION_TITLE } from "./court-overview";

// Thống kê dùng sân theo kỳ (Tuần / Tháng / Năm). Đổi kỳ chỉ gọi lại /stats.

type Stats = components["schemas"]["ResourceStatsOut"];
type Period = Stats["period"];
const PERIODS: { key: Period; label: string }[] = [
  { key: "week", label: "Tuần" },
  { key: "month", label: "Tháng" },
  { key: "year", label: "Năm" },
];

export function CourtStats({ code }: { code: string }) {
  const [period, setPeriod] = useState<Period>("week");
  // undefined = đang tải, null = lỗi
  const [stats, setStats] = useState<Stats | null | undefined>(undefined);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải lại khi đổi kỳ
    setStats(undefined);
    api
      .GET("/api/v1/booking/resources/{code}/stats", { params: { path: { code }, query: { period } } })
      .then(({ data }) => live && setStats(data ?? null))
      .catch(() => live && setStats(null));
    return () => {
      live = false;
    };
  }, [code, period, attempt]);

  const figures = stats
    ? [
        { label: "Lấp đầy", value: `${formatNumber(Math.round(stats.occupancy_pct))}%` },
        { label: "Giờ đã bán", value: formatNumber(stats.booked_hours) },
        { label: "Lượt đặt", value: formatNumber(stats.bookings_count) },
        { label: "Doanh thu", value: formatVnd(stats.revenue) },
      ]
    : [];

  return (
    <section aria-labelledby="court-stats" className={SECTION}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="court-stats" className={SECTION_TITLE}>Thống kê dùng sân</h3>
        <div role="group" aria-label="Chọn kỳ thống kê" className="grid grid-cols-3 gap-1 rounded-lg bg-background p-1">
          {PERIODS.map((p) => (
            <button
              key={p.key}
              type="button"
              aria-pressed={period === p.key}
              onClick={() => setPeriod(p.key)}
              className={cn("h-11 rounded-md px-3 text-sm font-semibold transition-colors focus-ring sm:h-8", period === p.key ? "bg-surface text-primary-hover shadow-card" : "text-muted")}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
      {stats === undefined ? (
        <Skeleton className="h-28 w-full" />
      ) : stats === null ? (
        <p className="flex flex-wrap items-center gap-2 text-sm text-danger">
          Không tải được thống kê.
          <button type="button" onClick={() => setAttempt((n) => n + 1)} className="min-h-11 font-semibold underline focus-ring sm:min-h-0">Thử lại</button>
        </p>
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-4">
            {figures.map((x) => (
              <div key={x.label} className="flex flex-col gap-0.5">
                <dt className="text-ui text-muted">{x.label}</dt>
                <dd className="text-lg font-bold tabular-nums">{x.value}</dd>
              </div>
            ))}
          </dl>
          <p className="text-ui text-muted">
            {formatDayMonthYear(stats.start)} – {formatDayMonthYear(stats.end)} · Tính đến {formatDayMonthYear(stats.until)} · Lượt đặt không gồm vé sự kiện.
          </p>
        </>
      )}
    </section>
  );
}
