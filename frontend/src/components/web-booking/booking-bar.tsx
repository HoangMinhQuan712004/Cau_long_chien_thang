"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { formatVnd } from "@/lib/format";
import type { Group } from "./booking-summary";
import { PendingCheckoutBanner } from "./pending-banner";

// Thanh "Bạn đang chọn" dính đáy (điện thoại) / dính dưới khung lịch (từ sm): tổng giờ, tổng tiền, nút Tiếp theo;
// mở rộng để xem danh sách khối đã chọn (T-028 AC7).

type Props = { groups: Group[]; totalHours: number; total: number; holdMinutes: number; disabled: boolean; onNext: () => void };

export function BookingBar({ groups, totalHours, total, holdMinutes, disabled, onNext }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <section
      data-bottom-bar
      aria-label="Bạn đang chọn"
      // Điện thoại: nền xanh kéo dài xuống dưới đáy (after:) ⇒ không lộ dải trắng dưới thanh khi thanh công cụ trình duyệt co / giãn
      className={cn(
        "fixed inset-x-0 bottom-0 z-40 rounded-t-[20px] bg-appbar text-surface shadow-[0_-6px_24px_rgb(0_0_0/0.25)]",
        "after:absolute after:inset-x-0 after:top-full after:h-screen after:bg-appbar",
        "sm:sticky sm:bottom-3 sm:rounded-2xl sm:shadow-lg sm:after:hidden",
      )}
    >
      {/* Còn lượt chờ thanh toán: hàng nhắc dính liền mép trên thanh này (thẻ nổi chung bị ẩn khi có data-bottom-bar) */}
      <PendingCheckoutBanner part="inline" sync={false} />
      {/* Điện thoại: thanh gọn (người dùng 03/11) – đệm, chữ và nút nhỏ hơn; từ sm giữ cỡ cũ */}
      <div className="px-4 pt-1 pb-[max(0.5rem,env(safe-area-inset-bottom))] sm:py-3">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls="bar-list"
          className="mx-auto mb-0.5 flex h-5 w-full items-center justify-center rounded text-surface/80 hover:text-surface focus-ring sm:mb-1 sm:h-6"
        >
          <span className="sr-only">{open ? "Thu gọn danh sách khung đã chọn" : "Xem danh sách khung đã chọn"}</span>
          <svg aria-hidden viewBox="0 0 20 20" className={cn("size-5 transition-transform motion-reduce:transition-none", open && "rotate-180")} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="m5 12.5 5-5 5 5" />
          </svg>
        </button>
        {open ? (
          <ul id="bar-list" className="mb-3 max-h-40 space-y-1 overflow-y-auto rounded-xl bg-surface/10 p-3 text-sm">
            {groups.map((g) => (
              <li key={g.code} className="flex items-baseline justify-between gap-3">
                <span className="min-w-0">
                  <b>{g.name}</b>: {g.ranges}
                </span>
                <span className="shrink-0 tabular-nums">{formatVnd(g.amount)}</span>
              </li>
            ))}
            <li className="pt-1 text-xs text-surface/80">Khung giờ được giữ {holdMinutes} phút sau khi bạn bấm thanh toán.</li>
          </ul>
        ) : null}
        <div className="flex items-center gap-3">
          <div className="min-w-0 flex-1 leading-tight">
            <p className="text-[11px] text-surface/80 sm:text-xs">
              Tổng giờ: <b className="text-surface">{totalHours}</b>
            </p>
            <p className="text-base font-bold tabular-nums sm:text-lg">
              <span className="text-[11px] font-normal text-surface/80 sm:text-xs">Tổng tiền: </span>
              {formatVnd(total)}
            </p>
          </div>
          <Button variant="cta" onClick={onNext} disabled={disabled} className="h-11 min-w-28 px-4 text-xs sm:h-12 sm:min-w-36 sm:px-6 sm:text-sm">
            Tiếp theo
          </Button>
        </div>
      </div>
    </section>
  );
}
