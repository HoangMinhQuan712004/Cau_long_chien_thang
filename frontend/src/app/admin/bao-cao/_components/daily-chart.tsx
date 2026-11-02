"use client";

import {
  Bar,
  CartesianGrid,
  ComposedChart,
  LabelList,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Dictionary } from "@/i18n/dictionaries";
import { formatDayMonth } from "@/lib/format";
import { cn } from "@/lib/cn";
import { CHART_HEIGHT, CHART_COLOR as C, ChartTip, millionAxisLabel, millionTicks } from "./chart-parts";
import { fill, isWeekend, millions, money, WEEKDAY_SHORT, weekdayIndex } from "./report-format";
import type { ReportOverview } from "@/lib/api/server";

/** Quá số ngày này ⇒ không ghi số trên điểm, chỉ hiện khi rê (BR-014). */
const LABEL_MAX_DAYS = 14;

type Props = {
  daily: ReportOverview["daily"];
  /** "07/10 – 13/10" cho tên biểu đồ (trình đọc màn hình). */
  range: string;
  t: Dictionary["report"]["daily"];
};

const dayLabel = (date: string) => `${WEEKDAY_SHORT[weekdayIndex(date)]} ${formatDayMonth(date)}`;

/** Trục ngang 2 dòng: dd/mm, dưới là thứ; T7, CN chữ xanh. */
function DayTick({ x = 0, y = 0, payload }: { x?: number; y?: number; payload?: { value: string } }) {
  const date = payload?.value ?? "";
  const weekend = isWeekend(date);
  return (
    <text x={x} y={y + 12} textAnchor="middle" fontSize={11} fill={weekend ? C.primary : C.axis}>
      <tspan x={x}>{formatDayMonth(date)}</tspan>
      <tspan x={x} dy={13} fontWeight={weekend ? 600 : 400}>{WEEKDAY_SHORT[weekdayIndex(date)]}</tspan>
    </text>
  );
}

/** Doanh thu theo ngày: đường + điểm, đường trung bình nét đứt, nền nhạt T7/CN, ngày cao nhất tô đặc (BR-014). */
export function DailyChart({ daily, range, t }: Props) {
  const total = daily.reduce((sum, d) => sum + d.revenue, 0);
  const average = daily.length ? total / daily.length : 0;
  const ticks = millionTicks(Math.max(...daily.map((d) => d.revenue), average));
  const top = ticks[ticks.length - 1];
  // Nhiều ngày cùng cao nhất ⇒ ngày muộn nhất; kỳ chưa có doanh thu ⇒ không đánh dấu
  const peak = total > 0 ? daily.reduce((best, d, i) => (d.revenue >= daily[best].revenue ? i : best), 0) : -1;
  // Cột nền cao hết trục ở T7, CN (cột đặt trước đường nên nằm dưới)
  const rows = daily.map((d) => ({ ...d, weekend: isWeekend(d.date) ? top : 0 }));
  // Kỳ chưa có doanh thu: không ghi "0,0" chồng lên đường, không vẽ trung bình (trùng trục 0)
  const showLabels = daily.length <= LABEL_MAX_DAYS && total > 0;

  return (
    <div className="flex flex-col gap-2.5">
      <div role="img" aria-label={fill(t.chartLabel, { range })} className={cn("w-full", CHART_HEIGHT)}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 22, right: 8, bottom: 0, left: 0 }} barCategoryGap={0}>
            <CartesianGrid vertical={false} stroke={C.grid} />
            <XAxis
              dataKey="date"
              tick={<DayTick />}
              tickLine={false}
              axisLine={{ stroke: C.grid }}
              height={36}
              // ≤ 7 ngày ghi đủ mọi ngày; dài hơn thì tự bỏ bớt cho khỏi chồng chữ
              interval={daily.length <= 7 ? 0 : "preserveStartEnd"}
              minTickGap={8}
            />
            <YAxis
              ticks={ticks}
              domain={[0, top]}
              tickFormatter={millionAxisLabel}
              tick={{ fontSize: 11, fill: C.axis }}
              tickLine={false}
              axisLine={false}
              width={44}
            />
            <Bar dataKey="weekend" fill={C.soft} isAnimationActive={false} activeBar={false} />
            {total > 0 ? <ReferenceLine y={average} stroke={C.average} strokeDasharray="5 4" strokeWidth={1.5} /> : null}
            <Tooltip
              cursor={false}
              isAnimationActive={false}
              content={({ active, payload }) => {
                const row = payload?.[0]?.payload as (typeof rows)[number] | undefined;
                return active && row ? <ChartTip text={fill(t.point, { day: dayLabel(row.date), amount: money(row.revenue) })} /> : null;
              }}
            />
            <Line
              dataKey="revenue"
              stroke={C.primary}
              strokeWidth={2.5}
              isAnimationActive={false}
              // > 14 ngày: bỏ chấm từng ngày (30 chấm dính nhau), chỉ hiện chấm khi rê
              dot={daily.length > LABEL_MAX_DAYS ? false : ({ cx, cy, index }) => (
                <circle
                  key={index}
                  cx={cx}
                  cy={cy}
                  r={index === peak ? 5 : 3.5}
                  fill={index === peak ? C.primary : C.surface}
                  stroke={C.primary}
                  strokeWidth={2}
                />
              )}
              activeDot={{ r: 6, fill: C.primary, stroke: C.surface, strokeWidth: 2 }}
            >
              {showLabels ? (
                <LabelList
                  dataKey="revenue"
                  position="top"
                  offset={10}
                  fontSize={11}
                  fontWeight={700}
                  fill={C.text}
                  // Viền trắng quanh chữ: nhãn đè lên đường trung bình / đường nối vẫn đọc rõ
                  stroke={C.surface}
                  strokeWidth={3}
                  paintOrder="stroke"
                  formatter={(v) => millions(Number(v))}
                />
              ) : null}
            </Line>
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Chú giải bằng chữ + ký hiệu (không chỉ dựa vào màu) */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        <span className="flex items-center gap-1.5">
          <i aria-hidden className="h-0.5 w-4 rounded-full bg-primary" />
          {t.legendLine}
        </span>
        <span className="flex items-center gap-1.5">
          <i aria-hidden className="w-4 border-t-2 border-dashed border-accent-fg" />
          {fill(t.legendAverage, { avg: millions(average) })}
        </span>
        <span className="flex items-center gap-1.5">
          <i aria-hidden className="size-3 rounded-xs border bg-primary-softer" />
          {t.legendWeekend}
        </span>
      </div>
      <p className="text-xs sm:text-ui">
        <b className="font-semibold tabular-nums">{fill(t.total, { total: money(total) })}</b>
        {peak >= 0 ? (
          <span className="text-muted tabular-nums">
            {" · "}
            {fill(t.peak, { day: dayLabel(daily[peak].date), amount: money(daily[peak].revenue) })}
          </span>
        ) : null}
      </p>
    </div>
  );
}
