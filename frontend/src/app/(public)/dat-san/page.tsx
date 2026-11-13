import type { Metadata } from "next";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";
import { LocalBusinessJsonLd } from "@/components/local-business-json-ld";
import { openingText, WithPublicPrices } from "@/components/public-prices";
import { PageBanner } from "@/components/member-area/page-banner";
import { WebBookingFlow } from "@/components/web-booking/booking-flow";
import { BOOKING_BANNER_SLOT } from "@/components/web-booking/types";
import { getDictionary } from "@/i18n/dictionaries";
import { todayVn } from "@/lib/format";
import { getBranding, getCurrentUser } from "@/lib/api/server";
import { memberHome } from "@/lib/safe-next";
import { siteDescription } from "@/lib/site";

// Trang chính của web (người dùng 04/11): "/" chuyển vĩnh viễn (308) tới đây, nên trang mang SEO của trang chủ cũ:
// tiêu đề có tên sân, mô tả, canonical và JSON-LD SportsActivityLocation (tên, địa chỉ, giờ mở cửa, khoảng giá).
export async function generateMetadata(): Promise<Metadata> {
  const { name } = await getBranding();
  return {
    title: { absolute: `${name} – Đặt sân cầu lông online` },
    description: `${siteDescription(name)} Xem lịch trống theo thời gian thực và đặt sân, thanh toán trước bằng chuyển khoản QR.`,
    alternates: { canonical: "/dat-san" },
  };
}

// Phần khung (tiêu đề, mô tả, header, footer) prerender tĩnh; lịch và ngày hôm nay (giờ Việt Nam) đọc lúc chạy trong <Suspense>.
export default async function BookingPage({ searchParams }: PageProps<"/dat-san">) {
  const info = await getBranding();
  return (
    <div>
      <Suspense fallback={null}>
        <MemberRedirect searchParams={searchParams} />
      </Suspense>
      <Suspense fallback={null}>
        <WithPublicPrices>{(data) => <LocalBusinessJsonLd data={data} info={info} />}</WithPublicPrices>
      </Suspense>
      {/* Banner xanh lưới giống màn Đặt sân khu hội viên (người dùng 12/11): tràn hết bề ngang, sát header; bộ chọn ngày
          được bước 1 đưa vào chỗ trống cuối banner (step1-layouts.tsx) */}
      <div className="relative left-1/2 -mt-8 mb-6 w-screen -translate-x-1/2 sm:mb-8">
        <PageBanner
          mobileTitle
          title={<span className="text-cta">Đặt sân</span>}
          subtitle={
            // Một dòng thông tin sân cho khách và cho Google (thay phần giới thiệu của trang chủ cũ)
            <>
              {info.name} · {info.address}
              <Suspense fallback={null}>
                <WithPublicPrices>{(data) => (openingText(data) ? ` · Mở cửa ${openingText(data)}` : null)}</WithPublicPrices>
              </Suspense>
            </>
          }
        >
          <div id={BOOKING_BANNER_SLOT} className="mx-auto max-w-6xl px-4 empty:hidden not-empty:pb-4 lg:not-empty:pb-14" />
        </PageBanner>
      </div>
      <Suspense fallback={<p className="text-muted">Đang tải lịch sân…</p>}>
        <FlowLoader searchParams={searchParams} />
      </Suspense>
    </div>
  );
}

/** Hội viên đã đăng nhập không dùng trang công khai (người dùng 13/11) ⇒ vào khu hội viên, giữ ngày / booking. */
async function MemberRedirect({ searchParams }: Pick<PageProps<"/dat-san">, "searchParams">) {
  // Đọc cookie lúc chạy (trong <Suspense>) ⇒ vỏ trang vẫn prerender cho khách / SEO; không có phiên thì không gọi backend
  const jar = await cookies();
  if (jar.has("admin_session") || !jar.has("access_token")) return null;
  const user = await getCurrentUser();
  if (user?.must_change_password) redirect("/doi-mat-khau");
  if ((user as { is_member?: boolean } | null)?.is_member !== true) return null;
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) if (typeof value === "string") query.set(key, value);
  redirect(memberHome(query.size ? `/dat-san?${query}` : "/dat-san"));
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
  const [{ phoneVerify }, venue] = await Promise.all([getDictionary(), getBranding()]);
  return <WebBookingFlow initialDate={initialDate} today={today} venue={venue} texts={phoneVerify} initialEvent={initialEvent} />;
}
