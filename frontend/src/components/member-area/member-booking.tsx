"use client";

import { PageBanner } from "@/components/member-area/page-banner";
import { type BookingVenue, WebBookingFlow } from "@/components/web-booking/booking-flow";
import type { Dictionary } from "@/i18n/dictionaries";
import { BOOKING_BANNER_SLOT } from "@/components/web-booking/types";
import { useMember } from "./member-shell";

/** /hoi-vien/dat-san (T-018 AC4): luồng /dat-san trong khung khu hội viên; họ tên + SĐT lấy từ hồ sơ (khóa), không OTP. */
export function MemberBooking({ initialDate, today, venue, texts, initialEvent }: { initialDate: string; today: string; venue: BookingVenue; texts: Dictionary["phoneVerify"]; initialEvent: string | null }) {
  const { me } = useMember();
  return (
    <>
      {/* Chữ "Đặt sân" cùng màu nút Đặt sân (vàng cta) */}
      <PageBanner flushOnMobile title={<span className="text-cta">Đặt sân</span>} subtitle="Đặt online, thanh toán trước bằng chuyển khoản QR">
        {/* Chỗ để bước 1 đưa bộ chọn ngày vào trong banner (một khối xanh, một lớp lưới) – step1-layouts.tsx */}
        <div id={BOOKING_BANNER_SLOT} className="mx-auto max-w-6xl px-4 empty:hidden not-empty:pb-4 lg:not-empty:pb-14" />
      </PageBanner>
      <div className="mx-auto max-w-6xl px-4 py-6 sm:py-8">
        <WebBookingFlow initialDate={initialDate} today={today} venue={venue} texts={texts} member={{ name: me.full_name, phone: me.phone }} initialEvent={initialEvent} />
      </div>
    </>
  );
}
