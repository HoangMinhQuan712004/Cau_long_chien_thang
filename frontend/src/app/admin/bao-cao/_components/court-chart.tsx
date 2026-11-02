"use client";

import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Dictionary } from "@/i18n/dictionaries";
import { CHART_COLOR as C, millionTicks } from "./chart-parts";
import { TipBridge, usePinTip } from "./chart-tip-layer";
import { fill, millions, money } from "./report-format";
import { ScrollChart } from "./scroll-chart";
import type { ReportOverview } from "@/lib/api/server";

type Court = ReportOverview["courts"][number];
type T = Dictionary["report"]["courts"];
type Props = {
  courts: Court[];
  /** "07/10 – 13/10" cho tên biểu đồ (trình đọc màn hình). */
  range: string;
  /** Tên vùng cuộn ngang. */
  scrollLabel: string;
  t: T;
};

/** Mỗi cột tối thiểu 72px (tên sân 2 dòng đọc được; nhiều sân ⇒ cuộn ngang); khe 20% mỗi bên ⇒ cột ≈ 43px. */
const MIN_STEP = 72;
const GAP = 0.2;
const PLOT_TOP = 22;
/** Trục ngang: tên tối đa 2 dòng + dòng "↓" (đủ cả khi màn lớn phóng chữ 112,5%). */
const AXIS_HEIGHT = 58;
/** Bề rộng ước tính 1 ký tự chữ 11px đậm (đủ an toàn cho số + "tr"). */
const CHAR_PX = 6.6;

type TickProps = {
  x?: number;
  y?: number;
  payload?: { value: string };
  /** Recharts truyền: bề rộng trục và số nhãn ⇒ bề rộng 1 cột. */
  width?: number;
  visibleTicksCount?: number;
  byCode: Map<string, Court>;
  lowest: Set<string>;
  tipText: (court: Court) => string;
};

/**
 * Dưới cột: tên sân tối đa 2 dòng (ngắt theo từ, dài hơn thì "…"), sân thấp nhất thêm "↓" đỏ dưới tên.
 * Rê hoặc chạm tên ⇒ hộp chú thích tên đầy đủ + số tiền.
 */
function CourtTick({ x = 0, y = 0, payload, width = 0, visibleTicksCount = 1, byCode, lowest, tipText }: TickProps) {
  const setTip = usePinTip();
  const court = byCode.get(payload?.value ?? "");
  if (!court) return null;
  const band = width / visibleTicksCount;
  const show = () => setTip({ x, y: y - 4, text: tipText(court) });
  return (
    <foreignObject x={x - band / 2} y={y - 4} width={band} height={AXIS_HEIGHT - 4}>
      <div
        // mouseover/out (không dùng enter/leave): nhãn trục recharts nằm trong portal, React không phát enter
        onMouseOver={show}
        onMouseOut={() => setTip(null)}
        onClick={show}
        className="flex flex-col items-center px-1 text-center text-xs/4"
      >
        <span className="line-clamp-2 wrap-break-word text-muted">{court.name}</span>
        {lowest.has(court.code) ? <b aria-hidden className="font-bold text-danger">↓</b> : null}
      </div>
    </foreignObject>
  );
}

/** Doanh thu theo sân: cột theo mã sân, nhãn "19,7 tr" khi đủ chỗ; sân thấp nhất cột nhạt + "↓" và dòng tóm tắt (BR-015). */
export function CourtChart({ courts, range, scrollLabel, t }: Props) {
  const total = courts.reduce((sum, c) => sum + c.revenue, 0);
  const ticks = millionTicks(Math.max(0, ...courts.map((c) => c.revenue)));
  const min = Math.min(...courts.map((c) => c.revenue));
  // Mọi sân bằng nhau (gồm cả kỳ chưa có doanh thu) ⇒ không đánh dấu; nhiều sân cùng thấp nhất ⇒ đánh dấu tất cả
  const hasLowest = courts.some((c) => c.revenue !== min);
  const lowestCourts = hasLowest ? courts.filter((c) => c.revenue === min) : [];
  const lowest = new Set(lowestCourts.map((c) => c.code));
  const byCode = new Map(courts.map((c) => [c.code, c]));
  // Hộp chú thích: tên đầy đủ (+ "ngừng hoạt động") · số tiền đầy đủ
  const tipText = (c: Court) =>
    fill(t.bar, { name: c.is_active ? c.name : `${c.name} ${t.inactive}`, amount: money(c.revenue) });
  const lowestNames = lowestCourts.map((c) => c.name).join(", ");
  const lowestText = lowestCourts.length === 1
    ? fill(t.lowestOne, { name: lowestNames, amount: money(min) })
    : fill(t.lowestMany, { n: lowestCourts.length, amount: money(min), names: lowestNames });

  return (
    <div className="flex flex-col gap-2.5">
      <ScrollChart
        count={courts.length}
        minStep={MIN_STEP}
        ticks={ticks}
        plotTop={PLOT_TOP}
        axisHeight={AXIS_HEIGHT}
        label={fill(t.chartLabel, { range })}
        scrollLabel={scrollLabel}
      >
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={courts} margin={{ top: PLOT_TOP, right: 4, bottom: 0, left: 0 }} barCategoryGap={`${GAP * 100}%`}>
            <CartesianGrid vertical={false} stroke={C.grid} />
            <XAxis
              dataKey="code"
              tick={<CourtTick byCode={byCode} lowest={lowest} tipText={tipText} />}
              tickLine={false}
              axisLine={{ stroke: C.grid }}
              height={AXIS_HEIGHT}
              interval={0}
            />
            {/* Trục dọc vẽ ở ScrollChart (đứng yên khi cuộn); trục ẩn ở đây chỉ để lưới theo đúng mốc */}
            <YAxis hide ticks={ticks} domain={[0, ticks[ticks.length - 1]]} />
            {/* Recharts chỉ lo vùng rê + nền cột; hộp chú thích vẽ ngoài khung cuộn (TipBridge) */}
            <Tooltip cursor={{ fill: C.soft }} isAnimationActive={false} content={() => null} />
            <TipBridge<Court> text={tipText} />
            <Bar dataKey="revenue" radius={[4, 4, 0, 0]} isAnimationActive={false}>
              {courts.map((c) => (
                <Cell key={c.code} fill={C.primary} fillOpacity={lowest.has(c.code) ? 0.4 : 1} />
              ))}
              {/* Nhãn 1 dòng, chỉ khi vừa bề rộng cột (không chồng nhãn bên cạnh); cột 0 đ để trống (rê vẫn thấy) */}
              <LabelList
                dataKey="revenue"
                content={({ x, y, width, value }) => {
                  const text = `${millions(Number(value))} tr`;
                  const band = Number(width) / (1 - 2 * GAP);
                  if (!Number(value) || text.length * CHAR_PX > band - 4) return null;
                  return (
                    <text
                      x={Number(x) + Number(width) / 2}
                      y={Number(y) - 6}
                      textAnchor="middle"
                      fontSize={11}
                      fontWeight={700}
                      fill={C.text}
                    >
                      {text}
                    </text>
                  );
                }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </ScrollChart>

      {/* Chú giải + tóm tắt sân thấp nhất thay cho chữ lặp dưới từng cột */}
      {lowestCourts.length ? (
        // Hiện đủ danh sách sân thấp nhất, tự xuống dòng (ký hiệu đứng đầu dòng đầu)
        <p className="flex min-w-0 items-start gap-1.5 text-xs text-muted sm:text-ui">
          <i aria-hidden className="mt-0.5 h-3 w-2.5 shrink-0 rounded-t-xs bg-primary/40" />
          <b aria-hidden className="font-bold text-danger">↓</b>
          <span className="min-w-0 wrap-break-word tabular-nums">{lowestText}</span>
        </p>
      ) : null}
      <p className="text-xs font-semibold tabular-nums sm:text-ui">
        {fill(t.total, { n: courts.length, total: money(total) })}
      </p>
    </div>
  );
}
