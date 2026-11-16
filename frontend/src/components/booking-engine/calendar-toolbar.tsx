"use client";

import { useState } from "react";
import { DatePicker } from "@/components/ui/date-picker";
import { CalendarPlusIcon, ChevronLeftIcon, ChevronRightIcon, SearchIcon } from "@/components/ui/icons";
import { Input } from "@/components/ui/input";
import { useDragScroll } from "@/hooks/use-drag-scroll";
import { normalizeBookingCode } from "@/lib/booking-code";
import { cn } from "@/lib/cn";
import { addDaysIso, formatLongDate } from "@/lib/format";
import { toolBtnCls } from "./ui";

// Thanh công cụ màn Đặt sân. Điện thoại: mỗi nhóm một hàng, nhịp 8px:
// (a) tiêu đề + Định kỳ · (b) ‹ ngày › Hôm nay · (c) ô tìm mã · (d) Hiển thị dạng segmented · (e) chú thích một dòng vuốt ngang.
// Từ lg: (a)(b)(c) chung một hàng; (d)(e) hàng dưới.

type Props = {
  date: string;
  today: string;
  onGoto: (date: string) => void;
  /** Có quyền booking.recurring ⇒ hiện nút; null ⇒ ẩn. */
  onRecurring: (() => void) | null;
  /** Tìm mã đơn / khối / sự kiện / vé; trả câu lỗi ("" = tìm thấy). */
  onSearch: (code: string) => Promise<string>;
  unpaidOnly: boolean;
  unpaidCount: number;
  onUnpaidOnly: (v: boolean) => void;
};

/** [màu ô, nhãn ngắn, giải thích, nhãn đủ từ sm] – nhãn ngắn để vừa một dòng trên điện thoại. */
const LEGEND: [string, string, string, string?][] = [
  ["border border-border-strong bg-surface", "Trống", "Ô trống, bấm để chọn"],
  ["bg-primary", "Đang chọn", "Ô đang chọn"],
  ["bg-blk-paid", "Đã đặt", "Đã đặt, đã thanh toán"],
  ["bg-blk-unpaid", "Chưa TT", "Đã đặt, chưa thanh toán", "Chưa thanh toán"],
  ["bg-blk-session", "Sự kiện", "Sự kiện (bán vé theo người)"],
  ["bg-cell-off", "Không bán", "Ngoài giờ mở cửa hoặc sân ngừng hoạt động"],
];

const iconBtn = cn(toolBtnCls, "w-8 shrink-0 px-0 before:-inset-x-1.5 sm:w-9 [&>svg]:size-4.5");
const segment = (active: boolean) =>
  cn(
    // Phần nhìn 32px; vùng chạm ẩn 40px + khung p-0.5 ⇒ ≥ 44px
    "relative inline-flex h-8 min-w-0 items-center justify-center rounded-md px-3 text-sm whitespace-nowrap focus-ring transition-colors before:absolute before:inset-x-0 before:-inset-y-1 disabled:opacity-50 motion-reduce:transition-none",
    active ? "bg-surface font-semibold text-primary shadow-card" : "text-muted enabled:hover:text-foreground",
  );

export function CalendarToolbar({ date, today, onGoto, onRecurring, onSearch, unpaidOnly, unpaidCount, onUnpaidOnly }: Props) {
  const [query, setQuery] = useState("");
  const [searchError, setSearchError] = useState("");
  // Chú thích tràn ⇒ vuốt / kéo ngang, mờ mép còn chữ ẩn
  const { ref: legendRef, edges: legendEdges } = useDragScroll<HTMLUListElement>();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const code = normalizeBookingCode(query);
    if (!code) return;
    setSearchError(await onSearch(code));
  }

  return (
    <div className="flex shrink-0 flex-col gap-2 sm:gap-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {/* (a) Tiêu đề + Định kỳ (điện thoại: icon + chữ ngắn, không vỡ dòng) */}
        <h1 className="text-xl font-bold sm:text-2xl">Đặt sân</h1>
        {onRecurring ? (
          <button
            type="button"
            onClick={onRecurring}
            aria-label="Đặt sân định kỳ"
            className={cn(toolBtnCls, "order-1 ml-auto gap-1.5 border-primary font-semibold whitespace-nowrap text-primary lg:order-last lg:ml-0 [&>svg]:size-4.5")}
          >
            <CalendarPlusIcon aria-hidden />
            <span className="sm:hidden">Định kỳ</span>
            <span className="hidden sm:inline">Đặt sân định kỳ</span>
          </button>
        ) : null}

        {/* (b) ‹ ngày › Hôm nay: điện thoại rộng hết hàng, ngày ở giữa */}
        <div className="order-2 flex w-full items-center gap-2 sm:w-auto lg:order-none">
          <button type="button" onClick={() => onGoto(addDaysIso(date, -1))} aria-label="Ngày trước" className={iconBtn}>
            <ChevronLeftIcon aria-hidden />
          </button>
          {/* Bấm vào ngày ⇒ lịch tháng (máy tính: popover; điện thoại: bảng trượt từ đáy) */}
          <DatePicker value={date} today={today} onChange={onGoto} className="min-w-0 flex-1 sm:w-48 sm:flex-none" />
          <span className="sr-only" aria-live="polite">
            {formatLongDate(date)}
          </span>
          <button type="button" onClick={() => onGoto(addDaysIso(date, 1))} aria-label="Ngày sau" className={iconBtn}>
            <ChevronRightIcon aria-hidden />
          </button>
          <button type="button" onClick={() => onGoto(today)} disabled={date === today} className={cn(toolBtnCls, "shrink-0 whitespace-nowrap")}>
            Hôm nay
          </button>
        </div>

        {/* (c) Tìm mã: kính lúp trong ô, chữ 16px trên điện thoại (iOS không tự phóng to) */}
        <form onSubmit={submit} role="search" className="order-3 flex w-full flex-wrap gap-2 sm:w-auto lg:order-none lg:ml-auto">
          <label htmlFor="code-search" className="sr-only">
            Tìm theo mã đơn, mã khối, sự kiện hoặc vé
          </label>
          <Input
            id="code-search"
            value={query}
            placeholder="Tìm mã BK-…"
            maxLength={40}
            startSlot={<SearchIcon />}
            onChange={(e) => {
              setQuery(e.target.value);
              setSearchError("");
            }}
            aria-invalid={Boolean(searchError) || undefined}
            aria-describedby={searchError ? "code-search-error" : undefined}
            // Ô tìm cao 36px (chữ 16px trên điện thoại để iOS không phóng to)
            className="min-w-0 flex-1 sm:w-56 sm:flex-none [&_input]:h-9 sm:[&_input]:h-9"
          />
          <button type="submit" className={cn(toolBtnCls, "h-9 shrink-0")}>
            Tìm
          </button>
          {searchError ? (
            <p id="code-search-error" role="alert" className="w-full text-xs text-danger">
              {searchError}
            </p>
          ) : null}
        </form>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row-reverse sm:items-center sm:gap-4">
        {/* (d) Hiển thị: segmented, điện thoại vừa khít bề ngang */}
        <div role="group" aria-label="Hiển thị" className="flex shrink-0 items-center gap-2">
          <span className="hidden text-sm text-muted sm:inline">Hiển thị</span>
          <div className="grid flex-1 grid-cols-2 gap-0.5 rounded-lg bg-background p-0.5 sm:flex-none">
            <button type="button" onClick={() => onUnpaidOnly(false)} aria-pressed={!unpaidOnly} className={segment(!unpaidOnly)}>
              Tất cả
            </button>
            <button type="button" onClick={() => onUnpaidOnly(true)} disabled={unpaidCount === 0} aria-pressed={unpaidOnly} className={segment(unpaidOnly)}>
              Chưa thanh toán ({unpaidCount})
            </button>
          </div>
        </div>

        {/* (e) Chú thích: một dòng; thiếu chỗ thì vuốt ngang trong khung (mờ mép), trang không tràn.
            relative: chữ sr-only (absolute) nằm trong khung cuộn, không đẩy trang rộng ra */}
        <ul
          ref={legendRef}
          aria-label="Chú thích màu"
          className={cn(
            "scrollbar-none relative flex min-w-0 flex-1 gap-x-4 overflow-x-auto text-xs whitespace-nowrap text-muted",
            legendEdges.right && "[mask-image:linear-gradient(to_right,black_calc(100%-2rem),transparent)]",
            legendEdges.left && !legendEdges.right && "[mask-image:linear-gradient(to_left,black_calc(100%-2rem),transparent)]",
          )}
        >
          {LEGEND.map(([swatch, text, title, full]) => (
            <li key={text} className="inline-flex shrink-0 items-center gap-1.5 py-1" title={title}>
              <span aria-hidden className={`inline-block size-3 rounded-sm ${swatch}`} />
              {full ? (
                <>
                  <span className="sm:hidden">{text}</span>
                  <span className="hidden sm:inline">{full}</span>
                </>
              ) : (
                text
              )}
              <span className="sr-only">: {title}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
