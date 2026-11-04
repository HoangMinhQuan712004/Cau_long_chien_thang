import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { LocalBusinessJsonLd } from "@/components/local-business-json-ld";
import { PriceTable } from "@/components/price-table";
import { openingText, WithPublicPrices } from "@/components/public-prices";
import { fullAddress, phoneHref, site } from "@/lib/site";

export const metadata: Metadata = {
  alternates: { canonical: "/" },
};

// Vỏ trang (tiêu đề, địa chỉ, nút gọi) prerender tĩnh; mọi số liệu từ booking engine (giá, giờ mở cửa, số sân)
// nằm trong <Suspense> và đọc lúc chạy, nên build không cần backend.
export default function HomePage() {
  return (
    <>
      <Suspense fallback={null}>
        <WithPublicPrices>{(data) => <LocalBusinessJsonLd data={data} />}</WithPublicPrices>
      </Suspense>

      <section className="grid items-center gap-8 py-8 md:grid-cols-2">
        <div>
          <h1 className="text-3xl font-bold leading-tight sm:text-4xl">
            {site.name}
            <span className="block text-primary">Giá rõ ràng, đặt sân online</span>
          </h1>
          <p className="mt-4 text-muted">{site.description}</p>
          <p className="mt-2 text-sm text-muted">📍 {fullAddress}</p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link href="/dat-san" className="rounded-md bg-primary px-5 py-3 font-medium text-white">
              Đặt sân
            </Link>
            <Link href="/bang-gia" className="rounded-md border border-border px-5 py-3">
              Bảng giá
            </Link>
          </div>
          <p className="mt-3 text-sm text-muted">
            Đặt sân online, thanh toán bằng chuyển khoản QR — hoặc đặt tại quầy, gọi{" "}
            <a href={phoneHref} className="font-medium text-primary">
              {site.phone}
            </a>
            .
            <Suspense fallback={null}>
              <WithPublicPrices>{(data) => (openingText(data) ? ` Giờ mở cửa ${openingText(data)}.` : null)}</WithPublicPrices>
            </Suspense>
          </p>
        </div>
        <Suspense fallback={null}>
          <WithPublicPrices>
            {(data) => (
              <ul className="grid grid-cols-2 gap-3">
                {data?.resource_types.map((t) => (
                  <li key={t.code} className="rounded-lg border border-border bg-surface p-4">
                    <p className="font-semibold">{t.name}</p>
                    <p className="text-sm text-muted">{t.resource_count} sân</p>
                  </li>
                ))}
              </ul>
            )}
          </WithPublicPrices>
        </Suspense>
      </section>

      <section className="py-8">
        <h2 className="mb-4 text-2xl font-semibold">Bảng giá thuê sân</h2>
        <Suspense fallback={<p className="text-muted">Đang tải bảng giá…</p>}>
          <WithPublicPrices>{(data) => <PriceTable data={data} />}</WithPublicPrices>
        </Suspense>
      </section>
    </>
  );
}
