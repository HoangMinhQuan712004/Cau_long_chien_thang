"use client";

import { ActionMenu } from "@/components/ui/action-menu";
import { IconButton } from "@/components/ui/icon-button";
import { CloseIcon } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import { toast } from "@/lib/feedback";
import { formatVnd } from "@/lib/format";
import { toolBtnCls } from "./ui";

// Thanh dưới khi đang chọn ô trên lưới Đặt sân.
// Điện thoại: một hàng thấp ~52px dính đáy: [✕] số khung · tiền [⋯ Tạo sự kiện] [Đặt sân]; nút khóa ⇒ một dòng lý do nhỏ phía trên.
// Từ sm: thẻ nổi bo góc, đủ chữ: tạm tính, Bỏ chọn / Tạo sự kiện / Đặt sân, dòng lý do khóa.

type Props = {
  count: number;
  total: number;
  /** Lý do không đặt được ("" = đặt được). */
  bookReason: string;
  /** null ⇒ không có quyền tạo sự kiện (ẩn nút); chuỗi = lý do không tạo được ("" = tạo được). */
  eventReason: string | null;
  onClear: () => void;
  onBook: () => void;
  onEvent: () => void;
};

const ESTIMATE = "Tạm tính theo bảng giá; giá chốt khi đặt.";

export function SelectionBar({ count, total, bookReason, eventReason, onClear, onBook, onEvent }: Props) {
  const reasons = [bookReason, eventReason ?? ""].filter(Boolean).join(" · ");
  // Menu ⋯ (điện thoại) không có mục khóa ⇒ bấm khi chưa tạo được thì báo lý do
  const tryEvent = () => (eventReason ? toast(eventReason, undefined, "info") : onEvent());

  return (
    <section
      data-bottom-bar
      aria-label="Khung đang chọn"
      className={cn(
        "sticky bottom-0 z-20 -mx-4 shrink-0 border-t border-border bg-surface px-3 pt-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] shadow-card",
        "sm:bottom-3 sm:mx-0 sm:rounded-2xl sm:border sm:p-3",
      )}
    >
      {bookReason ? <p className="mb-1 truncate text-2xs text-muted sm:hidden">{bookReason}</p> : null}
      <div className="flex items-center gap-2 sm:gap-4">
        <IconButton icon={<CloseIcon />} label="Bỏ chọn tất cả khung" onClick={onClear} className="sm:hidden" />
        <p className="min-w-0 flex-1 truncate text-sm tabular-nums" aria-live="polite" title={ESTIMATE}>
          <span className="font-semibold">{count} khung</span>
          <span aria-hidden> · </span>
          <span className="text-ui text-muted sm:text-sm sm:font-semibold sm:text-foreground">{formatVnd(total)}</span>
          <span className="ml-2 hidden text-xs text-muted sm:inline">{ESTIMATE}</span>
        </p>

        {eventReason !== null ? <ActionMenu label="Thao tác khác" items={[{ label: "Tạo sự kiện", onClick: tryEvent }]} className="sm:hidden" /> : null}
        <div className="hidden gap-2 sm:flex">
          <button type="button" onClick={onClear} className={cn(toolBtnCls, "px-4")}>
            Bỏ chọn
          </button>
          {eventReason !== null ? (
            <button
              type="button"
              onClick={onEvent}
              disabled={Boolean(eventReason)}
              title={eventReason || undefined}
              className={cn(toolBtnCls, "border-primary px-4 font-semibold text-primary disabled:cursor-not-allowed disabled:opacity-40")}
            >
              Tạo sự kiện
            </button>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onBook}
          disabled={Boolean(bookReason)}
          title={bookReason || undefined}
          className={cn(
            "relative inline-flex h-9 shrink-0 items-center justify-center rounded-lg bg-primary px-4 text-sm font-semibold whitespace-nowrap text-white",
            "focus-ring before:absolute before:inset-x-0 before:-inset-y-1 hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-40 sm:px-5",
          )}
        >
          Đặt sân
        </button>
      </div>
      {reasons ? <p className="mt-1.5 hidden text-xs text-muted sm:block">{reasons}</p> : null}
    </section>
  );
}
