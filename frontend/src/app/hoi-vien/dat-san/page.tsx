import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";
import { MemberBooking } from "@/components/member-area/member-booking";
import { getDictionary } from "@/i18n/dictionaries";
import { todayVn } from "@/lib/format";
import { site } from "@/lib/site";

export const metadata: Metadata = { title: "Đặt sân" };

// Cùng luồng với /dat-san: ngày hôm nay (giờ Việt Nam) đọc lúc chạy, trong <Suspense>.
export default function Page({ searchParams }: PageProps<"/hoi-vien/dat-san">) {
  return (
    <Suspense fallback={<p className="p-8 text-center text-muted">Đang tải lịch sân…</p>}>
      <Loader searchParams={searchParams} />
    </Suspense>
  );
}

async function Loader({ searchParams }: Pick<PageProps<"/hoi-vien/dat-san">, "searchParams">) {
  await connection();
  const sp = await searchParams;
  const today = todayVn();
  // `ngay` (cũ) hoặc `date` (liên kết đăng nhập quay về, T-023 AC18)
  const rawDate = typeof sp.date === "string" ? sp.date : sp.ngay;
  const wanted = typeof rawDate === "string" && /^\d{4}-\d{2}-\d{2}$/.test(rawDate) ? rawDate : today;
  const initialEvent = typeof sp.event === "string" && /^BK-\d{8}-\d{3}$/.test(sp.event) ? sp.event : null;
  const { phoneVerify } = await getDictionary();
  return <MemberBooking initialDate={wanted < today ? today : wanted} today={today} hotline={site.phone} texts={phoneVerify} initialEvent={initialEvent} />;
}
