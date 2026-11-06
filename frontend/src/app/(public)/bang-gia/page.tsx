import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { PriceTable } from "@/components/price-table";
import { openingText, WithPublicPrices } from "@/components/public-prices";
import { getBranding } from "@/lib/api/server";
import { phoneHref } from "@/lib/site";

export async function generateMetadata(): Promise<Metadata> {
  const { name } = await getBranding();
  return {
    title: "Bảng giá thuê sân cầu lông",
    description: `Bảng giá thuê sân cầu lông tại ${name} theo khung giờ thấp điểm, cao điểm, ngày thường, cuối tuần và Lễ, Tết.`,
    alternates: { canonical: "/bang-gia" },
  };
}

// Vỏ trang prerender tĩnh; bảng giá và giờ mở cửa đọc lúc chạy từ booking engine (xem WithPublicPrices).
export default async function PricePage() {
  const { phone } = await getBranding();
  return (
    <article className="space-y-6">
      <h1 className="text-3xl font-bold">Bảng giá thuê sân</h1>
      <Suspense fallback={<p className="text-muted">Đang tải bảng giá…</p>}>
        <WithPublicPrices>
          {(data) => (
            <>
              <PriceTable data={data} />
              {openingText(data) ? (
                <p className="text-sm text-muted">
                  Giờ mở cửa: {openingText(data)} (giờ mở cửa có thể khác nhau giữa các sân).
                </p>
              ) : null}
            </>
          )}
        </WithPublicPrices>
      </Suspense>
      <p className="text-sm text-muted">Giá tính theo giờ, đồng/giờ. Đặt cố định hằng tuần vui lòng liên hệ {phone}.</p>
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-surface p-4 text-sm">
        <Link href="/dat-san" className="rounded-md bg-primary px-5 py-2.5 font-medium text-white">
          Đặt sân
        </Link>
        <p>
          Hoặc đặt tại quầy, gọi{" "}
          <a href={phoneHref(phone)} className="font-semibold text-primary">
            {phone}
          </a>
          .
        </p>
      </div>
    </article>
  );
}
