"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CourtGrid, cellKey, type GridCell, type GridRow } from "@/components/court-grid/court-grid";
import { vnDate, vnMinutes } from "@/lib/format";
import type { Block } from "./block";
import type { Calendar, CalendarBlock, Selection } from "./types";

// Lưới đặt sân của admin / nhân viên (T-025): adapter `Calendar` → `CourtGrid` dùng chung với trang khách.
// Chọn ô bằng cách bấm từng ô; kéo chuột để cuộn. Khối đã đặt hiện tên + 4 số cuối SĐT + mã đơn (điện thoại ẩn mã đơn, xem ở popup).

const pad2 = (n: number) => String(n).padStart(2, "0");
const mmss = (sec: number) => `${pad2(Math.floor(sec / 60))}:${pad2(Math.floor(sec % 60))}`;
/** "Lan · …0725": chỉ 4 số cuối, không hiện SĐT đầy đủ trên lưới. */
const phoneTail = (phone: string | null | undefined) => {
  const d = (phone ?? "").replace(/\D/g, "");
  return d.length >= 4 ? `…${d.slice(-4)}` : "";
};

/** Ô bán được (đang hoạt động, trong giờ mở cửa, chưa có khối) – không xét giờ đã qua. */
export function isSellable(calendar: Calendar, code: string, hour: number): boolean {
  const res = calendar.resources.find((r) => r.code === code);
  if (!res || !res.is_active || res.off_hours.includes(hour) || !calendar.columns.includes(hour)) return false;
  return !calendar.blocks.some((b) => b.resource_codes.includes(code) && hour >= b.start_hour && hour < b.end_hour);
}

/** Gom ô đã chọn thành khối theo từng sân (đúng thứ tự hiển thị), giờ liền nhau nối thành một khối. */
export function selectionBlocks(calendar: Calendar, selected: ReadonlySet<string>): Block[] {
  const out: Block[] = [];
  for (const r of calendar.resources) {
    const hours = calendar.columns.filter((h) => selected.has(cellKey(r.code, h)));
    let start: number | null = null;
    let prev = 0;
    for (const h of hours) {
      if (start === null) start = prev = h;
      else if (h === prev + 1) prev = h;
      else {
        out.push({ resource_code: r.code, start_hour: start, end_hour: prev + 1 });
        start = prev = h;
      }
    }
    if (start !== null) out.push({ resource_code: r.code, start_hour: start, end_hour: prev + 1 });
  }
  return out;
}

export const EVENT_RECT_HINT = "Sự kiện cần các sân liền nhau, cùng khung giờ liền nhau";

/** Vùng chọn là hình chữ nhật (sân liền nhau × một dải giờ liền nhau) ⇒ dùng được cho "Tạo sự kiện" (AC7). */
export function selectionRect(calendar: Calendar, selected: ReadonlySet<string>, date: string): Selection | null {
  const rowIdx = calendar.resources.map((r, i) => (calendar.columns.some((h) => selected.has(cellKey(r.code, h))) ? i : -1)).filter((i) => i >= 0);
  if (!rowIdx.length || rowIdx.some((v, k) => k > 0 && v !== rowIdx[k - 1] + 1)) return null;
  const hoursOf = (code: string) => calendar.columns.filter((h) => selected.has(cellKey(code, h)));
  const hours = hoursOf(calendar.resources[rowIdx[0]].code);
  if (!hours.length || hours.some((v, k) => k > 0 && v !== hours[k - 1] + 1)) return null;
  for (const i of rowIdx) {
    const hs = hoursOf(calendar.resources[i].code);
    if (hs.length !== hours.length || hs.some((v, k) => v !== hours[k])) return null;
  }
  return { resourceCodes: rowIdx.map((i) => calendar.resources[i].code), date, startHour: hours[0], endHour: hours[hours.length - 1] + 1 };
}

type Props = {
  calendar: Calendar;
  selected: ReadonlySet<string>;
  /** false ⇒ chỉ xem (ngày đã qua, không đủ quyền đặt ở ngày này). */
  selectable: boolean;
  unpaidOnly?: boolean;
  highlightCode?: string | null;
  onToggle: (code: string, hour: number) => void;
  onClear: () => void;
  onBlockClick: (block: CalendarBlock, el: HTMLElement) => void;
  /** Giữ chỗ hết hạn trên màn hình – cha nên tải lại lịch. */
  onHoldExpired?: () => void;
};

export function AdminGrid({ calendar, selected, selectable, unpaidOnly = false, highlightCode = null, onToggle, onClear, onBlockClick, onHoldExpired }: Props) {
  const { columns, resources, date } = calendar;

  // Đồng hồ bám giờ server (tránh lệch đồng hồ máy): mỗi giây khi có giữ chỗ, mỗi 30 giây khi xem hôm nay
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
  const blocks = useMemo(() => calendar.blocks.filter((b) => !(b.type === "hold" && b.expires_at && Date.parse(b.expires_at) <= nowMs)), [calendar.blocks, nowMs]);
  const expiredSeen = useRef(false);
  const expiredCount = calendar.blocks.length - blocks.length;
  useEffect(() => {
    if (expiredCount > 0 && !expiredSeen.current) {
      expiredSeen.current = true;
      onHoldExpired?.();
    }
    if (expiredCount === 0) expiredSeen.current = false;
  }, [expiredCount, onHoldExpired]);

  const rows = useMemo<GridRow[]>(() => {
    const isPast = (h: number) => isPastDay || (date === today && (h + 1) * 60 <= nowMin);
    return resources.map((res) => {
      const cells: Record<number, GridCell | undefined> = {};
      for (const h of columns) cells[h] = !res.is_active || res.off_hours.includes(h) ? { kind: "off" } : isPast(h) ? { kind: "past" } : { kind: "free", price: res.hour_prices?.[String(h)] ?? null };
      blocks.forEach((b, i) => {
        if (!b.resource_codes.includes(res.code)) return;
        const hit = !!highlightCode && (b.code === highlightCode || b.order_code === highlightCode);
        const key = `${b.type}:${b.code ?? b.order_code ?? i}`;
        const dim = unpaidOnly && (b.type === "booking" ? b.payment_status !== "unpaid" : b.type === "session" ? !b.unpaid_tickets : true);
        const common = { kind: "block" as const, key, dim, highlight: hit, onClick: (el: HTMLElement) => onBlockClick(b, el) };
        let cell: GridCell;
        if (b.type === "session") {
          cell = {
            ...common,
            tone: "session",
            lines: [`Sự kiện · ${b.name ?? ""}`, `${b.taken}/${b.capacity}${b.is_full ? " · Đủ chỗ" : ""}`, <span key="c" className="hidden font-mono text-2xs opacity-80 sm:inline">{b.code}</span>],
            aria: `sự kiện ${b.name ?? ""}, ${b.taken ?? 0} trên ${b.capacity ?? 0} người, xem chi tiết`,
            title: b.name ?? b.code ?? "",
          };
        } else if (b.type === "hold") {
          const left = b.expires_at ? Math.max(0, (Date.parse(b.expires_at) - nowMs) / 1000) : 0;
          cell = { ...common, tone: "hold", lines: ["Giữ chỗ", <span key="t" className="tabular-nums">{mmss(left)}</span>, "Đặt online"], aria: `giữ chỗ đặt online, còn ${Math.ceil(left)} giây` };
        } else {
          const status = b.payment_status;
          const tail = phoneTail(b.phone);
          const order = b.order_code ?? b.code;
          cell = {
            ...common,
            tone: status === "paid" ? "paid" : status === "uncollectible" ? "bad" : "unpaid",
            lines: [
              `${b.customer_name ?? ""}${tail ? ` · ${tail}` : ""}`,
              status === "unpaid" ? "Chưa thanh toán" : status === "uncollectible" ? "Không thu được" : null,
              <span key="o" className="hidden font-mono text-2xs opacity-80 sm:inline">{order}</span>,
            ].filter((l) => l !== null),
            aria: `${b.customer_name ?? "khách"}, ${status === "paid" ? "đã thanh toán" : status === "uncollectible" ? "không thu được" : "chưa thanh toán"}, mã đơn ${order}, xem chi tiết`,
            title: `${b.customer_name ?? ""} · ${order}${b.order_code && b.code ? ` (khối ${b.code})` : ""}`,
          };
        }
        for (let h = b.start_hour; h < b.end_hour; h++) if (h in cells) cells[h] = cell;
      });
      return { code: res.code, name: res.name, sub: `${res.code}${res.is_active ? "" : " · Ngừng"}`, muted: !res.is_active, cells };
    });
  }, [resources, columns, blocks, date, today, nowMin, isPastDay, unpaidOnly, highlightCode, nowMs, onBlockClick]);

  return (
    <CourtGrid
      label={`Lịch ngày ${date}`}
      columns={columns}
      rows={rows}
      selected={selected}
      selectable={selectable}
      onToggle={onToggle}
      onClear={onClear}
      mergeBlocks
      size="roomy"
      hourLabel={(h) => `${pad2(h)}:00`}
      nowAt={date === today ? nowMin / 60 : null}
      scrollToHour={date === today ? Math.floor(nowMin / 60) - 2 : null}
      scrollKey={date}
      // Màn Đặt sân (md+) đặt lưới trong cột flex cao bằng màn hình ⇒ khung co lại và cuộn dọc bên trong
      className="md:min-h-0"
    />
  );
}
