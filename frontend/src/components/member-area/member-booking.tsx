"use client";

import { PageBanner } from "@/components/member-area/page-banner";
import { WebBookingFlow } from "@/components/web-booking/booking-flow";
import type { Dictionary } from "@/i18n/dictionaries";
import { useMember } from "./member-shell";

/** /hoi-vien/dat-san (T-018 AC4): luồng /dat-san trong khung khu hội viên; họ tên + SĐT lấy từ hồ sơ (khóa), không OTP. */
export function MemberBooking({ initialDate, today, hotline, texts, initialEvent }: { initialDate: string; today: string; hotline: string; texts: Dictionary["phoneVerify"]; initialEvent: string | null }) {
  const { me } = useMember();
  return (
    <>
      <PageBanner title="Đặt sân" subtitle="Đặt online, thanh toán trước bằng chuyển khoản QR" />
      <div className="mx-auto max-w-6xl px-4 py-6 sm:py-8">
        <WebBookingFlow initialDate={initialDate} today={today} hotline={hotline} texts={texts} member={{ name: me.full_name, phone: me.phone }} initialEvent={initialEvent} />
      </div>
    </>
  );
}
