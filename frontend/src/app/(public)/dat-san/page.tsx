import type { Metadata } from "next";
import { Suspense } from "react";
import { BookingBoard } from "@/components/booking/booking-board";
import { getVenueConfig } from "@/lib/api/server";
import { site } from "@/lib/site";

export const metadata: Metadata = {
  title: "Đặt sân cầu lông online",
  description: `Xem lịch trống theo thời gian thực và đặt sân cầu lông tại ${site.name}.`,
  alternates: { canonical: "/dat-san" },
};

export default async function BookingPage() {
  const config = await getVenueConfig();
  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Đặt sân</h1>
      {/* Lịch trống thay đổi liên tục nên tải phía client; Suspense vì board dùng ngày hiện tại */}
      <Suspense fallback={<p className="text-muted">Đang tải lịch sân…</p>}>
        <BookingBoard maxAdvanceDays={config?.max_advance_days ?? 30} />
      </Suspense>
    </div>
  );
}
