import type { Metadata } from "next";
import Link from "next/link";
import { PriceTable } from "@/components/price-table";
import { getPriceRules } from "@/lib/api/server";
import { site } from "@/lib/site";

export const metadata: Metadata = {
  title: "Bảng giá thuê sân cầu lông",
  description: `Bảng giá thuê sân cầu lông tại ${site.name} theo khung giờ, ngày thường và cuối tuần.`,
  alternates: { canonical: "/bang-gia" },
};

export default async function PricePage() {
  const rules = await getPriceRules();
  return (
    <article className="space-y-6">
      <h1 className="text-3xl font-bold">Bảng giá thuê sân</h1>
      <PriceTable rules={rules} />
      <p className="text-sm text-muted">
        Giá đã bao gồm đèn và nước uống. Đặt cố định hằng tuần vui lòng liên hệ {site.phone}.
      </p>
      <Link href="/dat-san" className="inline-block rounded-md bg-primary px-5 py-3 text-surface">
        Đặt sân ngay
      </Link>
    </article>
  );
}
