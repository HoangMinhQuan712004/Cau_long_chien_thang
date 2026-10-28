import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";
import { WebBookingFlow } from "@/components/web-booking/booking-flow";
import { todayVn } from "@/lib/format";
import { site } from "@/lib/site";

export const metadata: Metadata = {
  title: "Đặt sân cầu lông online",
  description: `Xem lịch trống theo thời gian thực và đặt sân cầu lông tại ${site.name}, thanh toán trước bằng chuyển khoản QR.`,
  alternates: { canonical: "/dat-san" },
};

// Phần khung (tiêu đề, mô tả, header, footer) prerender tĩnh; lịch và ngày hôm nay (giờ Việt Nam) đọc lúc chạy trong <Suspense>.
export default function BookingPage({ searchParams }: PageProps<"/dat-san">) {
  return (
    <div className="space-y-4">
      <h1 className="text-3xl font-bold">Đặt sân</h1>
      <Suspense fallback={<p className="text-muted">Đang tải lịch sân…</p>}>
        <FlowLoader searchParams={searchParams} />
      </Suspense>
    </div>
  );
}

async function FlowLoader({ searchParams }: Pick<PageProps<"/dat-san">, "searchParams">) {
  await connection();
  const sp = await searchParams;
  const today = todayVn();
  const wanted = typeof sp.ngay === "string" && /^\d{4}-\d{2}-\d{2}$/.test(sp.ngay) ? sp.ngay : today;
  // Không cho mở ngày đã qua (kể cả qua liên kết cũ / lưu trong tab).
  const initialDate = wanted < today ? today : wanted;
  return <WebBookingFlow initialDate={initialDate} today={today} hotline={site.phone} />;
}
