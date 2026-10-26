import type { Metadata } from "next";
import { Suspense } from "react";
import { HolidaysCard } from "@/components/admin/holidays-card";
import { PriceEditor } from "@/components/admin/price-editor";
import { SanTabs } from "@/components/admin/san-tabs";
import { authedApi } from "@/lib/api/server";
import { todayVn } from "@/lib/format";

export const metadata: Metadata = { title: "Bảng giá" };

export default function PricesAdminPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Sân &amp; bảng giá</h1>
      <SanTabs active="prices" />
      <Suspense fallback={<p className="text-muted">Đang tải…</p>}>
        <Prices />
      </Suspense>
    </div>
  );
}

async function Prices() {
  const api = await authedApi();
  const year = Number(todayVn().slice(0, 4));
  const [prices, resources, days] = await Promise.all([
    api.GET("/api/v1/booking/prices"),
    api.GET("/api/v1/booking/resources"),
    api.GET("/api/v1/booking/special-days", { params: { query: { year } } }),
  ]);
  if (prices.response.status === 403 || resources.response.status === 403) {
    return <p className="text-muted">Chỉ chủ sân mới xem được mục này.</p>;
  }
  if (prices.error || resources.error || days.error || !prices.data || !resources.data || !days.data) {
    throw new Error("Không tải được bảng giá");
  }

  return (
    <div className="space-y-6">
      {/* key = version: sau khi lưu / tải lại, bản nháp được dựng mới từ dữ liệu server */}
      <PriceEditor key={prices.data.version} table={prices.data} resources={resources.data.items} />
      <HolidaysCard year={year} items={days.data} />
    </div>
  );
}
