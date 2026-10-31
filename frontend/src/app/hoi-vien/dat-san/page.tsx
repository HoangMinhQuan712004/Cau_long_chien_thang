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
  const wanted = typeof sp.ngay === "string" && /^\d{4}-\d{2}-\d{2}$/.test(sp.ngay) ? sp.ngay : today;
  const { phoneVerify } = await getDictionary();
  return <MemberBooking initialDate={wanted < today ? today : wanted} today={today} hotline={site.phone} texts={phoneVerify} />;
}
