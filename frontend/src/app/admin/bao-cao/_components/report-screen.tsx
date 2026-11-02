"use client";

import { useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { DateRangeKey, DateRangeValue } from "@/components/ui/date-range";
import { ResetIcon } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";
import { formatDayMonth, formatDayMonthYear, formatTime, vnDate } from "@/lib/format";
import { CapacityHeatmap } from "./capacity-heatmap";
import { ChartCard, ChartSkeleton } from "./chart-parts";
import { CourtChart } from "./court-chart";
import { DailyChart } from "./daily-chart";
import { KpiCards } from "./kpi-cards";
import { PeriodFilter } from "./period-filter";
import { fill } from "./report-format";
import { type Period, presetPeriod, rangeError } from "./report-period";
import type { ReportOverview } from "@/lib/api/server";
import { useReport } from "./use-report";

type Props = {
  /** Số liệu kỳ Tuần server tải sẵn; null ⇒ lỗi (E-004). */
  initial: ReportOverview | null;
  /** Hôm nay theo giờ Việt Nam (server tính, tránh lệch khi hydrate). */
  today: string;
  t: Dictionary["report"];
};

/** Màn Báo cáo & phân tích: một bộ lọc kỳ cho cả màn; mở lại luôn về Tuần (kỳ không lưu URL, BR-002). */
export function ReportScreen({ initial, today, t }: Props) {
  const [period, setPeriod] = useState<Period>(() => presetPeriod("week", today));
  const [invalid, setInvalid] = useState<DateRangeKey | null>(null);
  const report = useReport(initial);
  const { data, isLoading, error } = report;

  const apply = (next: Period) => {
    setPeriod(next);
    setInvalid(null);
    void report.load(next.from, next.to);
  };
  const choosePreset = (mode: "week" | "month") => {
    if (period.mode === mode && !invalid) return;
    apply(presetPeriod(mode));
  };
  const chooseRange = (range: DateRangeValue, key: DateRangeKey) => {
    const err = rangeError(range.from, range.to);
    if (err) {
      // Giữ kỳ và số đang hiện; ô vừa chọn viền đỏ (BR-004)
      setInvalid(key);
      report.setRangeError(err);
    } else if (range.from === period.from && range.to === period.to) {
      setInvalid(null);
      report.setRangeError(null);
    } else apply({ mode: "custom", ...range });
  };
  // Làm mới: kỳ Tuần / Tháng tính lại theo hôm nay (để màn qua 0h), kỳ tự chọn giữ ngày (BR-011)
  const refresh = () => apply(period.mode === "custom" ? period : presetPeriod(period.mode));

  const shown = isLoading ? null : data;
  const rangeErr = error && error !== "load" ? error : null;
  const range = shown ? `${formatDayMonth(shown.period.from)} – ${formatDayMonthYear(shown.period.to)}` : "";
  // Lần đầu lỗi (chưa có số) ⇒ bỏ dòng mô tả thay vì khung chờ mãi
  const updated = data
    ? fill(t.updatedAt, { time: formatTime(data.computed_at), date: formatDayMonthYear(vnDate(data.computed_at)) })
    : null;
  // Điện thoại: bỏ câu mô tả (tiêu đề đã đủ nghĩa), dưới tiêu đề chỉ còn giờ cập nhật chữ nhỏ; từ sm có mô tả,
  // giờ cập nhật nằm cạnh nút Làm mới từ md
  const description = data ? (
    <>
      <span className="hidden sm:inline">{fill(t.description, { n: data.active_courts })}</span>
      {updated ? <span className="block tabular-nums md:hidden">{updated}</span> : null}
    </>
  ) : isLoading ? <Skeleton className="h-4 w-60 max-w-full sm:w-80" /> : null;

  return (
    <div aria-busy={isLoading} className="flex max-w-7xl flex-col gap-3 sm:gap-4 lg:gap-5">
      <PageHeader
        title={t.title}
        description={description}
        descriptionBelow
        aside={
          <div className="flex shrink-0 items-center gap-3">
            {updated ? <span className="hidden text-ui text-muted tabular-nums md:inline">{updated}</span> : null}
            {/* Điện thoại chỉ icon (chữ cho trình đọc màn hình), từ sm đủ chữ */}
            <Button variant="secondary" loading={isLoading} onClick={refresh} title={t.refresh}>
              <ResetIcon />
              <span className="sr-only sm:not-sr-only">{isLoading ? t.refreshing : t.refresh}</span>
            </Button>
          </div>
        }
      />
      <p role="status" className="sr-only">{isLoading ? t.loading : ""}</p>

      {error === "load" ? <Alert>{t.errors.load}</Alert> : null}

      <PeriodFilter
        period={period}
        today={today}
        error={rangeErr}
        invalid={invalid}
        onPreset={choosePreset}
        onRange={chooseRange}
        t={t}
      />

      {shown || isLoading ? (
        <>
          <KpiCards data={shown} t={t.kpi} />
          {shown && shown.revenue.current === 0 ? <Alert variant="info">{t.errors.empty}</Alert> : null}
          <div className="grid gap-3 lg:grid-cols-[3fr_2fr] lg:gap-4">
            <ChartCard
              title={t.daily.title}
              subtitle={shown ? fill(t.daily.subtitle, { range, n: shown.active_courts }) : null}
            >
              {shown ? <DailyChart daily={shown.daily} range={range} t={t.daily} /> : <ChartSkeleton />}
            </ChartCard>
            <ChartCard title={t.courts.title} subtitle={shown ? fill(t.courts.subtitle, { range }) : null}>
              {shown ? <CourtChart courts={shown.courts} range={range} t={t.courts} /> : <ChartSkeleton />}
            </ChartCard>
          </div>
          <ChartCard
            title={t.heatmap.title}
            subtitle={
              shown
                ? fill(shown.heatmap.mode === "weekday" ? t.heatmap.subtitleWeekday : t.heatmap.subtitle, {
                  range,
                  n: shown.active_courts,
                })
                : null
            }
          >
            {shown ? <CapacityHeatmap heatmap={shown.heatmap} t={t.heatmap} /> : <ChartSkeleton className={cn(`
              h-96
              sm:h-112
            `)} />}
          </ChartCard>
        </>
      ) : null}
    </div>
  );
}
