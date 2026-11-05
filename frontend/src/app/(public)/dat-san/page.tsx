import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";
import { LocalBusinessJsonLd } from "@/components/local-business-json-ld";
import { openingText, WithPublicPrices } from "@/components/public-prices";
import { WebBookingFlow } from "@/components/web-booking/booking-flow";
import { getDictionary } from "@/i18n/dictionaries";
import { todayVn } from "@/lib/format";
import { fullAddress, site } from "@/lib/site";

// Trang chính của web (người dùng 04/11): "/" chuyển vĩnh viễn (308) tới đây, nên trang mang SEO của trang chủ cũ:
// tiêu đề có tên sân, mô tả, canonical và JSON-LD SportsActivityLocation (tên, địa chỉ, giờ mở cửa, khoảng giá).
export const metadata: Metadata = {
  title: { absolute: `${site.name} – Đặt sân cầu lông online` },
  description: `${site.description} Xem lịch trống theo thời gian thực và đặt sân, thanh toán trước bằng chuyển khoản QR.`,
  alternates: { canonical: "/dat-san" },
};

// Phần khung (tiêu đề, mô tả, header, footer) prerender tĩnh; lịch và ngày hôm nay (giờ Việt Nam) đọc lúc chạy trong <Suspense>.
export default function BookingPage({ searchParams }: PageProps<"/dat-san">) {
  return (
    <div className="space-y-4">
      <Suspense fallback={null}>
        <WithPublicPrices>{(data) => <LocalBusinessJsonLd data={data} />}</WithPublicPrices>
      </Suspense>
      <div>
        <h1 className="text-3xl font-bold">Đặt sân</h1>
        {/* Một dòng thông tin sân cho khách và cho Google (thay phần giới thiệu của trang chủ cũ) */}
        <p className="mt-1 text-sm text-muted">
          {site.name} · {fullAddress}
          <Suspense fallback={null}>
            <WithPublicPrices>{(data) => (openingText(data) ? ` · Mở cửa ${openingText(data)}` : null)}</WithPublicPrices>
          </Suspense>
        </p>
      </div>
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
  // `ngay` (cũ) hoặc `date` (liên kết đăng nhập quay về, T-023 AC18)
  const rawDate = typeof sp.date === "string" ? sp.date : sp.ngay;
  const wanted = typeof rawDate === "string" && /^\d{4}-\d{2}-\d{2}$/.test(rawDate) ? rawDate : today;
  const initialEvent = typeof sp.event === "string" && /^BK-\d{8}-\d{3}$/.test(sp.event) ? sp.event : null;
  // Không cho mở ngày đã qua (kể cả qua liên kết cũ / lưu trong tab).
  const initialDate = wanted < today ? today : wanted;
  const { phoneVerify } = await getDictionary();
  return <WebBookingFlow initialDate={initialDate} today={today} hotline={site.phone} texts={phoneVerify} initialEvent={initialEvent} />;
}
