"use client";

import { useEffect, useRef, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { formatVnd } from "@/lib/format";

// CourtGrid (T-025 AC1): MỘT lưới đặt sân dùng chung cho /dat-san, /hoi-vien/dat-san và /admin/dat-san.
// Hàng = sân, cột = khung 1 giờ, cột "Sân" dính bên trái, cuộn ngang. Bấm ô trống để chọn / bỏ chọn (nhiều sân, nhiều giờ).
// Component không biết API nào: mỗi màn dựng `rows` bằng adapter của mình và quyết định bấm ô nào thì làm gì.

export type GridTone = "paid" | "unpaid" | "bad" | "mine" | "session" | "hold";

export type GridBlock = {
  kind: "block";
  /** Cùng khóa ở các giờ liền nhau trên một sân ⇒ gộp thành một khối (khi `mergeBlocks`). */
  key: string;
  tone: GridTone;
  /** Mỗi phần tử một dòng chữ trong khối. */
  lines: ReactNode[];
  /** Mô tả cho trình đọc màn hình, ví dụ "sân của bạn, xem chi tiết" (lưới tự thêm tên sân + giờ). */
  aria: string;
  title?: string;
  /** Có ⇒ khối bấm được (nhận phần tử để trả focus khi đóng hộp thoại). */
  onClick?: (el: HTMLElement) => void;
  /** Viền đậm (ví dụ "Có vé"). */
  ring?: boolean;
  /** Làm mờ (bộ lọc "Chưa thanh toán"). */
  dim?: boolean;
  /** Tô sáng (sau khi tìm mã). */
  highlight?: boolean;
};

export type GridCell =
  | { kind: "off" } // không bán (xám)
  | { kind: "past" } // đã qua giờ
  | { kind: "free"; price?: number | null }
  | GridBlock;

export type GridRow = {
  code: string;
  name: string;
  /** Dòng phụ dưới tên sân (chỉ hiện ở cỡ "roomy"). */
  sub?: string;
  muted?: boolean;
  /** Ô theo giờ bắt đầu. Thiếu = không bán. */
  cells: Record<number, GridCell | undefined>;
};

export const cellKey = (code: string, hour: number) => `${code}|${hour}`;

const TONE: Record<GridTone, string> = {
  paid: "bg-blk-paid text-blk-paid-fg border-transparent",
  unpaid: "bg-blk-unpaid text-blk-unpaid-fg border-transparent",
  bad: "bg-blk-bad text-blk-bad-fg border-transparent bg-[repeating-linear-gradient(135deg,transparent_0_6px,rgb(0_0_0/0.08)_6px_8px)]",
  mine: "bg-blk-mine text-blk-mine-fg border-transparent",
  session: "bg-blk-session text-blk-session-fg border-transparent",
  hold: "border-dashed border-blk-hold-fg bg-surface text-blk-hold-fg",
};

const ARROWS: Record<string, [number, number]> = { ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [-1, 0], ArrowDown: [1, 0] };
const pad2 = (n: number) => String(n).padStart(2, "0");
const focusRing = "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-primary";

type Props = {
  label: string;
  columns: number[];
  rows: GridRow[];
  /** Ô đang chọn, khóa `cellKey(code, hour)`. */
  selected: ReadonlySet<string>;
  /** false ⇒ ô trống chỉ xem (ngày đã qua, không đủ quyền…). */
  selectable: boolean;
  onToggle: (code: string, hour: number) => void;
  /** Esc: bỏ chọn tất cả. */
  onClear?: () => void;
  /** Đang tải / đang mở hộp thoại: khóa chọn ô. */
  busy?: boolean;
  mergeBlocks?: boolean;
  /** "compact": lưới khách (ô nhỏ); "roomy": lưới admin (ô to, đủ chỗ cho tên + SĐT). */
  size?: "compact" | "roomy";
  hourLabel?: (hour: number) => string;
  /** Vạch "bây giờ": giờ dạng số thực (14.5 = 14:30), null = ẩn. */
  nowAt?: number | null;
  /** Cuộn ngang tới cột giờ này khi `scrollKey` đổi (ví dụ đổi ngày). */
  scrollToHour?: number | null;
  scrollKey?: string;
};

export function CourtGrid({
  label,
  columns,
  rows,
  selected,
  selectable,
  onToggle,
  onClear,
  busy = false,
  mergeBlocks = false,
  size = "compact",
  hourLabel = (h) => `${h}h`,
  nowAt = null,
  scrollToHour = null,
  scrollKey,
}: Props) {
  const roomy = size === "roomy";
  const first = columns[0] ?? 0;
  const gridRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Cuộn tới giờ cần xem khi đổi ngày (admin: giờ hiện tại - 2 giờ)
  useEffect(() => {
    const sc = scrollRef.current;
    if (!sc) return;
    const el = scrollToHour == null ? null : sc.querySelector<HTMLElement>(`[data-col="${Math.max(first, scrollToHour)}"]`);
    const lab = sc.querySelector<HTMLElement>("[data-label]");
    sc.scrollLeft = el ? el.offsetLeft - (lab?.offsetWidth ?? 0) : 0;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- chỉ cuộn khi đổi ngày, không giật mỗi lần tải lại lịch
  }, [scrollKey]);

  const focusCell = (r: number, h: number) => gridRef.current?.querySelector<HTMLElement>(`button[data-cell][data-r="${r}"][data-h="${h}"]`)?.focus();
  function onCellKey(e: KeyboardEvent, r: number, h: number) {
    const dir = ARROWS[e.key];
    if (!dir) return;
    e.preventDefault();
    let nr = r + dir[0];
    let nh = h + dir[1];
    while (nr >= 0 && nr < rows.length && nh >= first && nh < first + columns.length) {
      const el = gridRef.current?.querySelector<HTMLElement>(`button[data-cell][data-r="${nr}"][data-h="${nh}"]`);
      if (el) {
        focusCell(nr, nh);
        return;
      }
      nr += dir[0];
      nh += dir[1];
    }
  }

  const rowH = roomy ? "h-16" : "h-11";
  const colW = "w-(--col)";
  const cellBase = `m-0.5 flex ${rowH} shrink-0 flex-col items-center justify-center rounded-md border text-[11px] leading-tight`;
  const vars = roomy ? "[--c0:8.5rem] [--col:5rem] sm:[--c0:10rem] sm:[--col:5.5rem]" : "[--c0:5.5rem] [--col:3.25rem] sm:[--c0:6.5rem] sm:[--col:3.5rem]";
  const headH = roomy ? "h-9" : "h-6";

  return (
    <div
      ref={scrollRef}
      onKeyDown={(e) => {
        if (e.key === "Escape" && selected.size && onClear) {
          e.preventDefault();
          onClear();
        }
      }}
      className={`relative overflow-x-auto ${roomy ? "rounded-lg border border-border bg-surface" : ""} ${busy ? "opacity-60" : ""}`}
      aria-busy={busy}
    >
      <div ref={gridRef} role="group" aria-label={label} className={`relative min-w-max ${vars}`}>
        <div className={`flex ${headH} text-xs text-muted ${roomy ? "border-b border-border" : ""}`}>
          <div data-label className={`sticky left-0 z-20 flex w-(--c0) shrink-0 items-center bg-surface ${roomy ? "border-r border-border px-3 font-medium" : "pr-2"}`}>
            Sân
          </div>
          {columns.map((h) => (
            <div
              key={h}
              data-col={h}
              className={`flex ${colW} shrink-0 items-center justify-center ${roomy ? "border-r border-border" : "pb-1"} ${nowAt != null && Math.floor(nowAt) === h ? "font-bold text-primary" : ""}`}
            >
              {hourLabel(h)}
            </div>
          ))}
        </div>

        {rows.map((row, r) => {
          const out: ReactNode[] = [];
          for (let i = 0; i < columns.length; ) {
            const h = columns[i];
            const cell = row.cells[h];
            const slot = `${row.name}, ${pad2(h)}:00 đến ${pad2(h + 1)}:00`;

            if (!cell || cell.kind === "off") {
              out.push(<div key={h} role="img" aria-label={`${slot}, không bán`} className={`${cellBase} w-[calc(var(--col)-0.25rem)] border-transparent bg-cell-off`} />);
              i++;
              continue;
            }
            if (cell.kind === "past") {
              out.push(<div key={h} role="img" aria-label={`${slot}, đã qua`} className={`${cellBase} w-[calc(var(--col)-0.25rem)] border-transparent bg-background`} />);
              i++;
              continue;
            }
            if (cell.kind === "block") {
              let span = 1;
              if (mergeBlocks) {
                while (i + span < columns.length) {
                  const next = row.cells[columns[i + span]];
                  if (next?.kind === "block" && next.key === cell.key) span++;
                  else break;
                }
              }
              const style: CSSProperties = { width: `calc(var(--col) * ${span} - 0.25rem)` };
              const cls = `${cellBase} ${TONE[cell.tone]} ${cell.ring ? "ring-2 ring-blk-session-fg ring-inset" : ""} ${cell.dim ? "opacity-35" : ""} ${
                cell.highlight ? "outline-2 outline-offset-1 outline-primary" : ""
              } ${roomy ? "items-start px-2 text-left text-xs" : "font-medium"} min-w-0 overflow-hidden`;
              const aria = `${row.name}, ${pad2(h)}:00 đến ${pad2(h + span)}:00, ${cell.aria}`;
              const body = cell.lines.map((l, k) => (
                <span key={k} className={`max-w-full truncate ${k === 0 && roomy ? "font-bold" : ""}`}>
                  {l}
                </span>
              ));
              out.push(
                cell.onClick ? (
                  <button
                    key={h}
                    type="button"
                    style={style}
                    aria-label={aria}
                    title={cell.title}
                    data-block={cell.key}
                    onClick={(e) => cell.onClick?.(e.currentTarget)}
                    className={`${cls} ${focusRing}`}
                  >
                    {body}
                  </button>
                ) : (
                  <div key={h} role="img" aria-label={aria} title={cell.title} data-block={cell.key} style={style} className={cls}>
                    {body}
                  </div>
                ),
              );
              i += span;
              continue;
            }

            // Ô trống
            const on = selected.has(cellKey(row.code, h));
            const lock = !selectable || busy;
            out.push(
              <button
                key={h}
                type="button"
                data-cell
                data-r={r}
                data-h={h}
                onClick={() => !lock && onToggle(row.code, h)}
                onKeyDown={(e) => onCellKey(e, r, h)}
                aria-pressed={on}
                aria-disabled={lock || undefined}
                aria-label={`${slot}, trống${cell.price != null ? `, ${formatVnd(cell.price)}` : ""}`}
                title={cell.price != null ? formatVnd(cell.price) : undefined}
                className={`${cellBase} touch-manipulation select-none w-[calc(var(--col)-0.25rem)] font-medium ${
                  on ? "border-primary bg-primary text-white" : `border-border bg-surface ${lock ? "" : "hover:bg-primary-softer"}`
                } ${lock ? "cursor-default" : ""} ${focusRing}`}
              >
                {on ? (roomy ? <span aria-hidden>✓</span> : `${h}h–${h + 1}h`) : null}
                {roomy && cell.price != null ? <span className={`text-[10px] tabular-nums ${on ? "" : "text-muted"}`}>{Math.round(cell.price / 1000)}k</span> : null}
              </button>,
            );
            i++;
          }
          return (
            <div key={row.code} className={`flex border-t border-border/60 ${row.muted ? "opacity-70" : ""}`}>
              <div className={`sticky left-0 z-10 flex w-(--c0) shrink-0 ${roomy ? "flex-col justify-center border-r border-border px-3 text-sm" : "items-center pr-2 text-sm"} bg-surface font-medium`}>
                <span className="truncate">{row.name}</span>
                {roomy && row.sub ? <span className="truncate text-xs font-normal text-muted">{row.sub}</span> : null}
              </div>
              {out}
            </div>
          );
        })}

        {nowAt != null && nowAt >= first && nowAt <= first + columns.length ? (
          <div
            aria-hidden
            className={`pointer-events-none absolute bottom-0 z-30 w-px bg-danger ${roomy ? "top-9" : "top-6"}`}
            style={{ left: `calc(var(--c0) + var(--col) * ${(nowAt - first).toFixed(3)})` }}
          />
        ) : null}
      </div>
    </div>
  );
}
