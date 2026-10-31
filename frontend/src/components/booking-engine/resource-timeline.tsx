"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { vnDate, vnMinutes } from "@/lib/format";
import { formatPhone } from "@/lib/phone";
import type { Calendar, CalendarBlock, Selection } from "./types";

// ResourceTimeline – lịch một ngày: hàng = tài nguyên (sân), cột = khung 1 giờ.
// Dùng lại được cho mọi loại tài nguyên: chỉ nhận dữ liệu `Calendar` + cấu hình, không biết "sân cầu lông".
// Chọn vùng: kéo chuột; chạm hai bước (chạm ô đầu rồi ô cuối) trên điện thoại / máy tính bảng; bàn phím (mũi tên + Enter).
// Server luôn kiểm lại mọi điều kiện khi lưu – FE chỉ chặn sớm cho dễ dùng.

export type SelectionMode = "single-row-today" | "multi-row";
export type RejectReason = "occupied" | "not-today" | "past-day";

type Props = {
  calendar: Calendar;
  selectionMode: SelectionMode;
  /** Chip "Chưa thanh toán": làm mờ khối không thuộc bộ lọc. */
  unpaidOnly?: boolean;
  /** Mã khối cần tô sáng (sau khi tìm mã). */
  highlightCode?: string | null;
  /** Khóa chọn ô (đang mở hộp thoại). */
  disabled?: boolean;
  onSelect: (selection: Selection) => void;
  onReject?: (reason: RejectReason) => void;
  onBlockClick: (block: CalendarBlock) => void;
  /** Giữ chỗ hết hạn trên màn hình – cha nên tải lại lịch. */
  onHoldExpired?: () => void;
};

type Cell = { r: number; h: number };
type Rect = { r0: number; r1: number; h0: number; h1: number };

const rectOf = (a: Cell, b: Cell): Rect => ({
  r0: Math.min(a.r, b.r),
  r1: Math.max(a.r, b.r),
  h0: Math.min(a.h, b.h),
  h1: Math.max(a.h, b.h),
});
const inRect = (rect: Rect, r: number, h: number) => r >= rect.r0 && r <= rect.r1 && h >= rect.h0 && h <= rect.h1;
const pad2 = (n: number) => String(n).padStart(2, "0");
const mmss = (sec: number) => `${pad2(Math.floor(sec / 60))}:${pad2(Math.floor(sec % 60))}`;

export function ResourceTimeline({
  calendar,
  selectionMode,
  unpaidOnly = false,
  highlightCode = null,
  disabled = false,
  onSelect,
  onReject,
  onBlockClick,
  onHoldExpired,
}: Props) {
  const { columns, resources, date } = calendar;
  const first = columns[0] ?? 0;
  const gridRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // ---- Đồng hồ: bám giờ server (tránh lệch đồng hồ máy), tick mỗi giây khi cần ----
  const offsetRef = useRef(0);
  const [nowMs, setNowMs] = useState(() => Date.parse(calendar.now));
  const hasHold = calendar.blocks.some((b) => b.type === "hold");
  const isToday = vnDate(calendar.now) === date;
  useEffect(() => {
    offsetRef.current = Date.parse(calendar.now) - Date.now();
    const tick = () => setNowMs(Date.now() + offsetRef.current);
    tick();
    if (!hasHold && !isToday) return;
    const id = setInterval(tick, hasHold ? 1000 : 30_000);
    return () => clearInterval(id);
  }, [calendar.now, hasHold, isToday]);

  const nowIso = new Date(nowMs).toISOString();
  const today = vnDate(nowIso);
  const nowMin = vnMinutes(nowIso);
  const isPastDay = calendar.is_past || date < today;

  // Khối giữ chỗ hết hạn thì biến mất ngay trên màn hình
  const blocks = useMemo(
    () => calendar.blocks.filter((b) => !(b.type === "hold" && b.expires_at && Date.parse(b.expires_at) <= nowMs)),
    [calendar.blocks, nowMs],
  );
  const expiredSeen = useRef(false);
  const expiredCount = calendar.blocks.length - blocks.length;
  useEffect(() => {
    if (expiredCount > 0 && !expiredSeen.current) {
      expiredSeen.current = true;
      onHoldExpired?.();
    }
    if (expiredCount === 0) expiredSeen.current = false;
  }, [expiredCount, onHoldExpired]);

  // ---- Trạng thái từng ô ----
  const occupied = useMemo(() => {
    const set = new Set<string>();
    for (const b of blocks) for (const code of b.resource_codes) for (let h = b.start_hour; h < b.end_hour; h++) set.add(`${code}|${h}`);
    return set;
  }, [blocks]);

  const isOff = (r: number, h: number) => {
    const res = resources[r];
    return !res.is_active || res.off_hours.includes(h);
  };
  const isPastCell = (h: number) => isPastDay || (date === today && (h + 1) * 60 <= nowMin);
  const isFree = (r: number, h: number) => !isOff(r, h) && !isPastCell(h) && !occupied.has(`${resources[r].code}|${h}`);
  const rectFree = (rect: Rect) => {
    for (let r = rect.r0; r <= rect.r1; r++) for (let h = rect.h0; h <= rect.h1; h++) if (!isFree(r, h)) return false;
    return true;
  };
  const selectable = !disabled && !isPastDay && (calendar.can.counter_book || calendar.can.create_session);

  const emit = (rect: Rect) => {
    onSelect({
      resourceCodes: resources.slice(rect.r0, rect.r1 + 1).map((x) => x.code),
      date,
      startHour: rect.h0,
      endHour: rect.h1 + 1,
    });
  };

  const guard = (): boolean => {
    if (isPastDay) {
      onReject?.("past-day");
      return false;
    }
    if (selectionMode === "single-row-today" && date !== today) {
      onReject?.("not-today");
      return false;
    }
    return true;
  };
  const clampRow = (from: Cell, to: Cell): Cell => (selectionMode === "single-row-today" ? { r: from.r, h: to.h } : to);

  // ---- Kéo chuột ----
  const [drag, setDrag] = useState<{ from: Cell; to: Cell } | null>(null);
  const dragRef = useRef<{ from: Cell; to: Cell } | null>(null);
  const mouseHandled = useRef(false);

  const cellAt = (x: number, y: number): Cell | null => {
    const el = document.elementFromPoint(x, y)?.closest<HTMLElement>("[data-cell]");
    if (!el) return null;
    return { r: Number(el.dataset.r), h: Number(el.dataset.h) };
  };

  useEffect(() => {
    if (!drag) return;
    const move = (e: PointerEvent) => {
      const cur = dragRef.current;
      if (!cur) return;
      const c = cellAt(e.clientX, e.clientY);
      if (!c) return;
      const to = clampRow(cur.from, c);
      if (to.r === cur.to.r && to.h === cur.to.h) return;
      // Vùng kéo dừng ở ô không trống đầu tiên: bỏ qua nếu chạm ô không hợp lệ
      if (rectFree(rectOf(cur.from, to))) {
        dragRef.current = { from: cur.from, to };
        setDrag(dragRef.current);
      }
    };
    const up = () => {
      const cur = dragRef.current;
      dragRef.current = null;
      setDrag(null);
      if (cur) emit(rectOf(cur.from, cur.to));
    };
    const cancel = () => {
      dragRef.current = null;
      setDrag(null);
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up, { once: true });
    document.addEventListener("pointercancel", cancel, { once: true });
    return () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", cancel);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- handler đọc trạng thái mới nhất qua closure của lần render hiện tại
  }, [drag === null]);

  const onPointerDown = (e: React.PointerEvent, c: Cell) => {
    if (e.pointerType === "touch" || e.button !== 0 || !selectable) return; // chạm: xử lý ở onClick (hai bước)
    e.preventDefault();
    mouseHandled.current = true;
    if (!guard()) return;
    dragRef.current = { from: c, to: c };
    setDrag(dragRef.current);
  };

  // ---- Chạm hai bước + bàn phím ----
  const [anchor, setAnchor] = useState<Cell | null>(null);
  const onCellClick = (c: Cell) => {
    if (mouseHandled.current) {
      mouseHandled.current = false;
      return;
    }
    if (!selectable || !guard()) return;
    if (!anchor) {
      setAnchor(c);
      return;
    }
    const to = clampRow(anchor, c);
    if (to.r === anchor.r && to.h === anchor.h) {
      setAnchor(null);
      emit(rectOf(anchor, anchor));
      return;
    }
    const rect = rectOf(anchor, to);
    if (rectFree(rect)) {
      setAnchor(null);
      emit(rect);
    } else {
      onReject?.("occupied");
      setAnchor(c);
    }
  };

  const focusCell = (r: number, h: number) =>
    gridRef.current?.querySelector<HTMLElement>(`button[data-cell][data-r="${r}"][data-h="${h}"]`)?.focus();
  const onKeyDown = (e: React.KeyboardEvent, c: Cell) => {
    const dir = { ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [-1, 0], ArrowDown: [1, 0] }[e.key];
    if (e.key === "Escape") {
      setAnchor(null);
      return;
    }
    if (!dir) return;
    e.preventDefault();
    let r = c.r + dir[0];
    let h = c.h + dir[1];
    while (r >= 0 && r < resources.length && h >= first && h < first + columns.length) {
      if (isFree(r, h)) {
        focusCell(r, h);
        return;
      }
      r += dir[0];
      h += dir[1];
    }
  };

  // ---- Cuộn tới giờ hiện tại (chỉ khi xem hôm nay) ----
  useEffect(() => {
    const sc = scrollRef.current;
    if (!sc) return;
    if (date !== vnDate(new Date().toISOString())) {
      sc.scrollLeft = 0;
      return;
    }
    const target = Math.max(first, Math.floor(vnMinutes(new Date().toISOString()) / 60) - 2);
    const el = sc.querySelector<HTMLElement>(`[data-col="${target}"]`);
    const label = sc.querySelector<HTMLElement>("[data-label]");
    sc.scrollLeft = el ? el.offsetLeft - (label?.offsetWidth ?? 0) : 0;
  }, [date, first]);

  const sel = drag ? rectOf(drag.from, drag.to) : anchor ? rectOf(anchor, anchor) : null;
  const pos = (s: number, e: number): React.CSSProperties => ({
    left: `calc(var(--c0) + var(--col) * ${s - first} + 3px)`,
    width: `calc(var(--col) * ${e - s} - 6px)`,
  });
  const nowLeft = `calc(var(--c0) + var(--col) * ${(nowMin / 60 - first).toFixed(3)})`;
  const nowHour = Math.floor(nowMin / 60);

  const blockStyle = (b: CalendarBlock) => {
    if (b.type === "session") return "bg-blk-session text-blk-session-fg border-transparent";
    if (b.type === "hold") return "border-dashed border-blk-hold-fg bg-surface text-blk-hold-fg";
    if (b.payment_status === "paid") return "bg-blk-paid text-blk-paid-fg border-transparent";
    if (b.payment_status === "uncollectible")
      return "bg-blk-bad text-blk-bad-fg border-transparent bg-[repeating-linear-gradient(135deg,transparent_0_6px,rgb(0_0_0/0.08)_6px_8px)]";
    return "bg-blk-unpaid text-blk-unpaid-fg border-transparent";
  };
  const isDim = (b: CalendarBlock) => {
    if (!unpaidOnly) return false;
    if (b.type === "booking") return b.payment_status !== "unpaid";
    if (b.type === "session") return !b.unpaid_tickets;
    return true;
  };

  return (
    <div ref={scrollRef} className="relative overflow-x-auto rounded-lg border border-border bg-surface">
      <div
        ref={gridRef}
        role="grid"
        aria-label={`Lịch ngày ${date}`}
        aria-rowcount={resources.length + 1}
        className="relative min-w-max [--c0:8.5rem] [--col:5rem] sm:[--c0:10rem] sm:[--col:5.5rem]"
        style={{ width: `calc(var(--c0) + var(--col) * ${columns.length})` }}
      >
        <div role="row" className="flex h-9 border-b border-border text-xs text-muted">
          <div data-label className="sticky left-0 z-20 flex w-(--c0) shrink-0 items-center border-r border-border bg-surface px-3 font-medium">
            Sân
          </div>
          {columns.map((h) => (
            <div
              key={h}
              data-col={h}
              role="columnheader"
              className={`flex w-(--col) shrink-0 items-center justify-center border-r border-border ${
                date === today && h === nowHour ? "font-bold text-primary" : ""
              }`}
            >
              {pad2(h)}:00
            </div>
          ))}
        </div>

        {resources.map((res, r) => (
          <div key={res.code} role="row" className={`relative flex h-16 border-b border-border last:border-b-0 ${res.is_active ? "" : "opacity-70"}`}>
            <div
              role="rowheader"
              className="sticky left-0 z-20 flex w-(--c0) shrink-0 flex-col justify-center border-r border-border bg-surface px-3 text-sm"
            >
              <span className="truncate font-medium">{res.name}</span>
              <span className="truncate text-xs text-muted">
                {res.code}
                {res.is_active ? "" : " · Ngừng"}
              </span>
            </div>
            {columns.map((h) => {
              const off = isOff(r, h);
              const past = isPastCell(h);
              const free = isFree(r, h);
              const selected = sel ? inRect(sel, r, h) : false;
              const base = "h-full w-(--col) shrink-0 border-r border-border";
              if (!free) {
                return (
                  <div
                    key={h}
                    role="gridcell"
                    aria-disabled
                    className={`${base} ${off ? "bg-cell-off" : past ? "bg-background" : ""}`}
                  />
                );
              }
              return (
                <button
                  key={h}
                  type="button"
                  data-cell
                  data-r={r}
                  data-h={h}
                  role="gridcell"
                  disabled={!selectable}
                  aria-label={`${res.name}, ${pad2(h)}:00 đến ${pad2(h + 1)}:00, trống`}
                  aria-selected={selected}
                  onPointerDown={(e) => onPointerDown(e, { r, h })}
                  onClick={() => onCellClick({ r, h })}
                  onKeyDown={(e) => onKeyDown(e, { r, h })}
                  className={`${base} touch-manipulation select-none ${
                    selected ? "bg-cell-sel" : selectable ? "bg-surface hover:bg-primary-softer" : "bg-surface"
                  } focus-visible:z-10 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary`}
                />
              );
            })}

            {blocks
              .filter((b) => b.resource_codes.includes(res.code))
              .map((b, i) => (
                <button
                  key={`${b.type}-${b.code ?? i}-${res.code}`}
                  type="button"
                  style={pos(b.start_hour, b.end_hour)}
                  onClick={() => onBlockClick(b)}
                  title={b.type === "booking" ? `${b.customer_name ?? ""} · ${b.order_code ?? b.code}${b.order_code && b.code ? ` (khối ${b.code})` : ""}` : (b.name ?? b.code ?? "")}
                  className={`absolute top-1 bottom-1 z-10 flex min-w-0 flex-col justify-center overflow-hidden rounded-md border px-2 text-left text-xs leading-tight ${blockStyle(b)} ${
                    isDim(b) ? "opacity-35" : ""
                  } ${highlightCode && (b.code === highlightCode || b.order_code === highlightCode) ? "ring-2 ring-primary ring-offset-1" : ""}`}
                >
                  <BlockText block={b} nowMs={nowMs} />
                </button>
              ))}
          </div>
        ))}

        {date === today && nowMin >= first * 60 && nowMin <= (first + columns.length) * 60 ? (
          <div aria-hidden className="pointer-events-none absolute top-9 bottom-0 z-30 w-px bg-danger" style={{ left: nowLeft }} />
        ) : null}
      </div>
      {anchor && !drag ? (
        <p role="status" className="sticky left-0 border-t border-border bg-surface px-3 py-2 text-xs text-muted">
          Đã chọn ô đầu. Chạm ô cuối để chọn khoảng, hoặc chạm lại ô này để đặt 1 giờ. Esc để bỏ chọn.
        </p>
      ) : null}
    </div>
  );
}

function BlockText({ block: b, nowMs }: { block: CalendarBlock; nowMs: number }) {
  if (b.type === "session") {
    return (
      <>
        <b className="truncate">Sự kiện · {b.name}</b>
        <span className="truncate">
          {b.taken}/{b.capacity}
          {b.is_full ? " · Đủ chỗ" : ""}
        </span>
        <span className="truncate font-mono text-[10px] opacity-80">{b.code}</span>
      </>
    );
  }
  if (b.type === "hold") {
    const left = b.expires_at ? Math.max(0, (Date.parse(b.expires_at) - nowMs) / 1000) : 0;
    return (
      <>
        <b>Giữ chỗ</b>
        <span className="tabular-nums" aria-label={`còn ${Math.ceil(left)} giây`}>
          {mmss(left)}
        </span>
        <span>Đặt online</span>
      </>
    );
  }
  const bad = b.payment_status === "uncollectible";
  return (
    <>
      <b className="flex min-w-0 items-center gap-1">
        <span className="truncate">{b.customer_name}</span>
        {b.payment_status === "unpaid" ? (
          <span className="shrink-0 rounded bg-black/10 px-1 text-[10px] font-semibold">Chưa TT</span>
        ) : null}
      </b>
      <span className="truncate tabular-nums">{bad ? "Không thu được" : b.phone ? formatPhone(b.phone) : null}</span>
      {/* Khối mang MÃ ĐƠN; mã khối chỉ hiện trong chi tiết (T-019 AC4) */}
      <span className="truncate font-mono text-[10px] opacity-80">{b.order_code ?? b.code}</span>
    </>
  );
}
