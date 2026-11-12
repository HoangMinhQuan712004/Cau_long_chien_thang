"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { BOOKING_BANNER_SLOT } from "./types";

// Bước 1 màn Đặt sân – bố cục người dùng chọn 12/11 ("tiêu đề thẻ"): bộ chọn ngày nằm trong banner xanh (một khối, một
// lớp lưới); thẻ trắng trồi nhẹ lên đáy banner: đầu thẻ "Lịch sân" + ngày đang xem | chú thích màu, giữa là lưới sân,
// chân thẻ là lưu ý (đặt online tạm ngưng). Chỉ trình bày – các phần do booking-flow dựng sẵn; logic chọn ô / giá / giữ chỗ không đổi.

export type Step1Parts = {
  dayStrip: React.ReactNode;
  dateLabel: string;
  legendItems: React.ReactNode;
  /** Lưu ý quan trọng (vd đặt online tạm ngưng); null ⇒ không hiện. */
  alert: string | null;
  grid: React.ReactNode;
  notice: React.ReactNode;
  /** Thanh tóm tắt dính đáy; null khi chưa chọn ô. */
  bar: React.ReactNode;
};


/** Bộ chọn ngày nằm TRONG banner (cổng React vào chỗ trống ở cuối banner) ⇒ một khối xanh, một lớp lưới.
 *  Trang không có chỗ (vd /dat-san công khai) ⇒ hiện tại chỗ trên nền xanh riêng. */
function InBanner({ children }: { children: React.ReactNode }) {
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tìm chỗ trong banner sau khi dựng
    setSlot(document.getElementById(BOOKING_BANNER_SLOT));
  }, []);
  if (slot) return createPortal(<div className="text-surface">{children}</div>, slot);
  return <div className="rounded-2xl bg-appbar p-3 text-surface sm:p-4 lg:pb-20">{children}</div>;
}

export function Step1Layout(p: Step1Parts) {
  return (
    <>
      <InBanner>
        {/* Điện thoại / tablet (kiểu app đặt sân, người dùng 12/11): bộ chọn ngày trong ô xanh đậm hơn, chú thích chữ trắng
            ngay dưới trên nền xanh; máy tính giữ như cũ */}
        <div className="max-lg:rounded-2xl max-lg:bg-black/15 max-lg:p-3">{p.dayStrip}</div>
        <ul aria-label="Chú thích màu" className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-sm lg:hidden">
          {p.legendItems}
        </ul>
      </InBanner>
      {/* Điện thoại: lưới sát mép màn, ngay dưới banner (không thẻ nổi); máy tính: thẻ trắng trồi nhẹ lên đáy banner */}
      <div className="relative -mx-4 -mt-6 bg-surface sm:-mt-8 lg:mx-0 lg:-mt-18 lg:overflow-hidden lg:rounded-2xl lg:shadow-card">
        <div className="hidden border-b border-border px-5 py-4 lg:flex lg:items-end lg:justify-between lg:gap-3">
          <div>
            <h2 className="text-lg font-extrabold tracking-tight">Lịch sân</h2>
            <p className="text-sm text-muted">{p.dateLabel}</p>
          </div>
          <ul aria-label="Chú thích màu" className="flex flex-wrap justify-end gap-x-4 gap-y-1.5 text-xs text-muted">
            {p.legendItems}
          </ul>
        </div>
        {p.alert ? (
          <p role="status" className="px-4 py-3 text-sm text-danger lg:hidden">
            <b className="font-semibold">Lưu ý:</b> {p.alert}
          </p>
        ) : null}
        <div className="lg:p-4">{p.grid}</div>
        {p.alert ? (
          <p role="status" className="hidden border-t border-border px-5 py-3 text-sm text-danger lg:block">
            {p.alert}
          </p>
        ) : null}
      </div>
      {p.notice}
      {p.bar}
    </>
  );
}
