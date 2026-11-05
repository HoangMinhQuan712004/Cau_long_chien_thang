import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";
import { HolidaysCard } from "@/components/admin/holidays-card";
import { PriceEditor } from "@/components/admin/price-editor";
import { SanTabs } from "@/components/admin/san-tabs";
import { adminPerms, authedApi } from "@/lib/api/server";
import { getDictionary } from "@/i18n/dictionaries";
import { can } from "../../_components/forbidden";
import { todayVn } from "@/lib/format";

export const metadata: Metadata = { title: "Bảng giá" };

export default function PricesAdminPage() {
  return (
    // Tiêu đề + tab chỉ hiện sau khi qua kiểm quyền (thiếu quyền chỉ còn dòng báo, như các trang khác)
    <Suspense fallback={<p className="text-muted">Đang tải…</p>}>
      <Prices />
    </Suspense>
  );
}

async function Prices() {
  // Thiếu quyền booking.config.manage ⇒ báo không có quyền, không gọi API (backend vẫn kiểm: 403 cũng báo như vậy)
  const [perms, { adminNav }] = await Promise.all([adminPerms(), getDictionary()]);
  const noPermission = adminNav.noPermission;
  if (!can(perms, "booking.config.manage")) return <p className="text-muted">{noPermission}</p>;
  const api = await authedApi();
  await connection(); // giờ hiện tại chỉ dùng ở request, không prerender
  const year = Number(todayVn().slice(0, 4));
  const [prices, resources, days] = await Promise.all([
    api.GET("/api/v1/booking/prices"),
    api.GET("/api/v1/booking/resources"),
    api.GET("/api/v1/booking/special-days", { params: { query: { year } } }),
  ]);
  if (prices.response.status === 403 || resources.response.status === 403) {
    return <p className="text-muted">{noPermission}</p>;
  }
  if (prices.error || resources.error || days.error || !prices.data || !resources.data || !days.data) {
    throw new Error("Không tải được bảng giá");
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold sm:text-2xl">Sân &amp; bảng giá</h1>
      <SanTabs active="prices" />
      {/* key = version: sau khi lưu / tải lại, bản nháp được dựng mới từ dữ liệu server */}
      <PriceEditor key={prices.data.version} table={prices.data} resources={resources.data.items} />
      <HolidaysCard year={year} items={days.data} />
    </div>
  );
}
