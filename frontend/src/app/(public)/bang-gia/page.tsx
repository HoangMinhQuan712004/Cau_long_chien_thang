import type { Metadata } from "next";
import { PriceTable } from "@/components/price-table";
import { getPublicPrices } from "@/lib/api/server";
import { phoneHref, site } from "@/lib/site";

export const metadata: Metadata = {
  title: "Bảng giá thuê sân cầu lông",
  description: `Bảng giá thuê sân cầu lông tại ${site.name} theo khung giờ thấp điểm, cao điểm, ngày thường, cuối tuần và Lễ, Tết.`,
  alternates: { canonical: "/bang-gia" },
};

export default async function PricePage() {
  const data = await getPublicPrices();
  const hours = data?.opening_hours;
  return (
    <article className="space-y-6">
      <h1 className="text-3xl font-bold">Bảng giá thuê sân</h1>
      <PriceTable data={data} />
      {hours?.earliest_open && hours.latest_close ? (
        <p className="text-sm text-muted">
          Giờ mở cửa: {hours.earliest_open.slice(0, 5)} – {hours.latest_close.slice(0, 5)} (giờ mở cửa có thể khác nhau giữa các sân).
        </p>
      ) : null}
      <p className="text-sm text-muted">Giá tính theo giờ, đồng/giờ. Đặt cố định hằng tuần vui lòng liên hệ {site.phone}.</p>
      <p className="rounded-lg border border-border bg-surface p-4 text-sm">
        Đặt sân tại quầy hoặc gọi{" "}
        <a href={phoneHref} className="font-semibold text-primary">
          {site.phone}
        </a>
        . Đặt sân trực tuyến sẽ sớm có.
      </p>
    </article>
  );
}
