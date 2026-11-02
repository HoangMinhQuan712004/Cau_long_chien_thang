"use client";

import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";
import { CHART_HEIGHT, CHART_COLOR as C, ChartTip, millionAxisLabel, millionTicks } from "./chart-parts";
import { fill, millions, money } from "./report-format";
import type { ReportOverview } from "@/lib/api/server";

type Court = ReportOverview["courts"][number];
type Props = {
  courts: Court[];
  /** "07/10 – 13/10" cho tên biểu đồ (trình đọc màn hình). */
  range: string;
  t: Dictionary["report"]["courts"];
};

type TickProps = { x?: number; y?: number; payload?: { value: string }; byCode: Map<string, Court>; lowest: Set<string>; label: string };

/** Dưới cột: tên sân; sân thấp nhất thêm dòng đỏ "↓ thấp nhất". */
function CourtTick({ x = 0, y = 0, payload, byCode, lowest, label }: TickProps) {
  const court = byCode.get(payload?.value ?? "");
  if (!court) return null;
  return (
    <text x={x} y={y + 12} textAnchor="middle" fontSize={11} fill={C.axis}>
      <tspan x={x}>{court.name}</tspan>
      {lowest.has(court.code) ? (
        <tspan x={x} dy={14} fill={C.danger} fontWeight={700}>{label}</tspan>
      ) : null}
    </text>
  );
}

/** Doanh thu theo sân: cột theo mã sân, nhãn "19,7 tr"; sân thấp nhất cột nhạt + "↓ thấp nhất" (BR-015). */
export function CourtChart({ courts, range, t }: Props) {
  const total = courts.reduce((sum, c) => sum + c.revenue, 0);
  const ticks = millionTicks(Math.max(0, ...courts.map((c) => c.revenue)));
  const min = Math.min(...courts.map((c) => c.revenue));
  // Mọi sân bằng nhau (gồm cả kỳ chưa có doanh thu) ⇒ không đánh dấu; nhiều sân cùng thấp nhất ⇒ đánh dấu tất cả
  const hasLowest = courts.some((c) => c.revenue !== min);
  const lowest = new Set(hasLowest ? courts.filter((c) => c.revenue === min).map((c) => c.code) : []);
  const byCode = new Map(courts.map((c) => [c.code, c]));

  return (
    <div className="flex flex-col gap-2.5">
      <div role="img" aria-label={fill(t.chartLabel, { range })} className={cn("w-full", CHART_HEIGHT)}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={courts} margin={{ top: 22, right: 4, bottom: 0, left: 0 }} barCategoryGap="28%">
            <CartesianGrid vertical={false} stroke={C.grid} />
            <XAxis dataKey="code" tick={<CourtTick byCode={byCode} lowest={lowest} label={t.lowest} />} tickLine={false} axisLine={{ stroke: C.grid }} height={38} interval={0} />
            <YAxis
              ticks={ticks}
              domain={[0, ticks[ticks.length - 1]]}
              tickFormatter={millionAxisLabel}
              tick={{ fontSize: 11, fill: C.axis }}
              tickLine={false}
              axisLine={false}
              width={44}
            />
            <Tooltip
              cursor={{ fill: C.soft }}
              isAnimationActive={false}
              content={({ active, payload }) => {
                const court = payload?.[0]?.payload as Court | undefined;
                if (!active || !court) return null;
                const name = court.is_active ? court.name : `${court.name} ${t.inactive}`;
                return <ChartTip text={fill(t.bar, { name, amount: money(court.revenue) })} />;
              }}
            />
            <Bar dataKey="revenue" radius={[4, 4, 0, 0]} isAnimationActive={false}>
              {courts.map((c) => (
                <Cell key={c.code} fill={C.primary} fillOpacity={lowest.has(c.code) ? 0.4 : 1} />
              ))}
              {/* Tự vẽ nhãn 1 dòng: nhãn mặc định ngắt dòng theo bề rộng cột ("8,9" / "tr") */}
              <LabelList
                dataKey="revenue"
                content={({ x, y, width, value }) => (
                  <text
                    x={Number(x) + Number(width) / 2}
                    y={Number(y) - 6}
                    textAnchor="middle"
                    fontSize={11}
                    fontWeight={700}
                    fill={C.text}
                  >
                    {`${millions(Number(value))} tr`}
                  </text>
                )}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs font-semibold tabular-nums sm:text-ui">
        {fill(t.total, { n: courts.length, total: money(total) })}
      </p>
    </div>
  );
}
