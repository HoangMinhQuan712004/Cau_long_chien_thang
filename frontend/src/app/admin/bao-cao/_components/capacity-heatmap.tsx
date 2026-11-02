"use client";

import { useState } from "react";
import { useDragScroll } from "@/hooks/use-drag-scroll";
import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";
import { formatDayMonth } from "@/lib/format";
import { dragScrollClass } from "./chart-parts";
import { decimal1, fill, hoursCount, round1, WEEKDAY_SHORT } from "./report-format";
import type { HeatCell, HeatColumn, ReportOverview } from "@/lib/api/server";

type T = Dictionary["report"]["heatmap"];

// 5 mức màu (BR-018): 0% · <40 · 40–<70 · 70–<90 · ≥90; 2 mức đậm nhất chữ trắng
const LEVEL_CLASS = [
  // 0%: nền xám rất nhạt, không viền (lưới nhẹ, không thành bảng kẻ ô)
  "bg-background text-muted",
  "bg-primary-soft",
  "bg-heat-mid",
  "bg-primary text-surface",
  "bg-primary-hover text-surface",
] as const;

/** Mức màu theo số đã làm tròn 1 chữ số (số đang hiện trong ô). */
function level(pct: number) {
  if (pct === 0) return 0;
  if (pct < 40) return 1;
  if (pct < 70) return 2;
  return pct < 90 ? 3 : 4;
}

const pad = (h: number) => String(h).padStart(2, "0");
const hourLabel = (h: number) => `${pad(h)}h–${pad(h + 1)}h`;
const columnLabel = (c: HeatColumn) =>
  c.date ? `${WEEKDAY_SHORT[c.weekday]} ${formatDayMonth(c.date)}` : WEEKDAY_SHORT[c.weekday];

/** Câu khi rê / đọc màn hình: "T7 10/10 · 17h–18h · 5/6 sân đã đặt". */
function cellTitle(cell: HeatCell, pct: number, col: HeatColumn, hour: number, t: T) {
  const vars = { day: columnLabel(col), hours: hourLabel(hour) };
  if (cell.open_hours === 0) return fill(t.closed, vars);
  if (col.date === null) return fill(t.cellWeekday, { ...vars, pct: `${decimal1(pct)}%` });
  const booked = hoursCount(cell.booked_hours);
  return fill(t.cellDay, { ...vars, booked, open: hoursCount(cell.open_hours), pct: `${decimal1(pct)}%` });
}

type Props = {
  heatmap: ReportOverview["heatmap"];
  /** Tên vùng cuộn ngang. */
  scrollLabel: string;
  t: T;
};

/** Heatmap công suất: hàng = khung 1 giờ, cột = ngày (kỳ ≤ 7 ngày) hoặc thứ; ô "–" khi không sân nào mở (BR-016, BR-017). */
export function CapacityHeatmap({ heatmap, scrollLabel, t }: Props) {
  const { columns, hours, cells } = heatmap;
  // Đã cuộn ngang ⇒ cột giờ có viền phải (biết là còn cột bị che); máy tính bấm giữ chuột kéo để cuộn
  const { ref, edges, isScrollable, isDragging } = useDragScroll<HTMLDivElement>();
  // Ô đang chạm / bấm ⇒ dòng chi tiết dưới bảng (điện thoại không có rê chuột)
  const [selected, setSelected] = useState<string | null>(null);
  // Cột giờ dính trái: nền đặc, không khoảng hở (bảng không border-spacing, khung cuộn không padding)
  // nên ô cuộn qua bị che hết; ô màu là khối bên trong ô bảng (p-0.5 tạo khe giữa các ô)
  // Điện thoại: cột giờ hẹp chỉ ghi giờ bắt đầu ("05h") ⇒ 7 cột vừa 375px không phải kéo
  const stickyCol = cn(
    "sticky left-0 z-1 w-8 bg-surface pr-1 text-left sm:w-18 sm:pr-1.5",
    edges.left && "border-r",
  );

  return (
    <div className="flex flex-col gap-3">
      {/* `relative`: chữ sr-only (absolute) trong ô bám khung cuộn, không làm tràn trang */}
      <div
        ref={ref}
        tabIndex={isScrollable ? 0 : undefined}
        role={isScrollable ? "region" : undefined}
        aria-label={isScrollable ? scrollLabel : undefined}
        className={cn("relative overflow-x-auto overscroll-x-contain focus-ring", dragScrollClass(isScrollable, isDragging))}
      >
        {/* Điện thoại: chữ 11px, số không kèm "%" (đơn vị ghi ở chú giải) ⇒ 7 cột vừa khung; từ sm ô rộng dần */}
        <table className={cn(`
          w-full table-fixed border-separate border-spacing-0 text-2xs tabular-nums
          sm:min-w-md sm:text-xs
        `)}>
          <thead>
            <tr>
              <th scope="col" className={stickyCol}>
                <span className="sr-only">{t.hours}</span>
              </th>
              {columns.map((c) => (
                // 2 dòng: thứ + ngày; cột hôm nay chữ đậm + "hôm nay" (các cột cùng rộng)
                <th
                  key={c.date ?? c.weekday}
                  scope="col"
                  className={cn("px-0.5 pb-1.5 align-bottom leading-tight", c.is_today ? "font-bold" : `
                    font-semibold text-muted
                  `)}
                >
                  <span className="block">{WEEKDAY_SHORT[c.weekday]}</span>
                  {c.date ? <span className="block font-normal">{formatDayMonth(c.date)}</span> : null}
                  {c.is_today ? <span className="block font-semibold text-primary">{t.today}</span> : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {hours.map((hour, r) => (
              <tr key={hour}>
                <th scope="row" className={cn(stickyCol, "font-medium whitespace-nowrap text-muted")}>
                  <span aria-hidden className="sm:hidden">{pad(hour)}h</span>
                  <span className="sr-only sm:not-sr-only">{hourLabel(hour)}</span>
                </th>
                {columns.map((col, c) => {
                  const cell = cells[r]?.[c] ?? { booked_hours: 0, open_hours: 0 };
                  const isClosed = cell.open_hours === 0;
                  const pct = isClosed ? 0 : round1((cell.booked_hours / cell.open_hours) * 100);
                  const label = cellTitle(cell, pct, col, hour, t);
                  return (
                    <td
                      key={col.date ?? col.weekday}
                      title={label}
                      onClick={() => setSelected((s) => (s === label ? null : label))}
                      className="p-px sm:p-0.5"
                    >
                      <span className={cn(
                        "flex h-7 items-center justify-center rounded-sm sm:h-8 sm:rounded-md",
                        selected === label && "ring-2 ring-foreground ring-inset",
                        isClosed ? "text-subtle" : LEVEL_CLASS[level(pct)],
                      )}>
                        <span aria-hidden>
                          {isClosed ? "–" : decimal1(pct)}
                          {isClosed ? null : <span className="hidden sm:inline">%</span>}
                        </span>
                        <span className="sr-only">{label}</span>
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Chi tiết ô đang chọn (giữ chỗ sẵn bằng dòng gợi ý ⇒ không nhảy bố cục) */}
      <p aria-live="polite" className={cn("text-xs tabular-nums sm:text-ui", selected ? `
        font-semibold
      ` : `text-subtle`)}>
        {selected ?? t.tapHint}
      </p>
      {/* Chú giải màu: Thấp → Cao; điện thoại ô không ghi "%" ⇒ nêu đơn vị */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted">
        <span className="font-semibold sm:hidden">{t.unit}</span>
        <span>{t.low}</span>
        {t.levels.map((label, i) => (
          <span key={label} className="flex items-center gap-1">
            <i aria-hidden className={cn("h-3 w-4 rounded-xs", LEVEL_CLASS[i], i === 0 && "border")} />
            {label}
          </span>
        ))}
        <span>{t.high}</span>
      </div>
    </div>
  );
}
