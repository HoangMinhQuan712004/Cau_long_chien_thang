import type { Metadata } from "next";
import { Suspense } from "react";
import { CourtsTable } from "@/components/admin/courts-table";
import { adminPerms, authedApi } from "@/lib/api/server";
import { getDictionary } from "@/i18n/dictionaries";
import { can } from "../_components/forbidden";

export const metadata: Metadata = { title: "Sân & bảng giá" };

export default function CourtsAdminPage() {
  return (
    // Tiêu đề + tab chỉ hiện sau khi qua kiểm quyền (thiếu quyền chỉ còn dòng báo, như các trang khác)
    <Suspense fallback={<p className="text-muted">Đang tải…</p>}>
      <Courts />
    </Suspense>
  );
}

async function Courts() {
  // Thiếu quyền booking.config.manage ⇒ báo không có quyền, không gọi API (backend vẫn kiểm: 403 cũng báo như vậy)
  const [perms, { adminNav, courts }] = await Promise.all([adminPerms(), getDictionary()]);
  const noPermission = adminNav.noPermission;
  if (!can(perms, "booking.config.manage")) return <p className="text-muted">{noPermission}</p>;
  const api = await authedApi();
  const [resources, prices] = await Promise.all([
    api.GET("/api/v1/booking/resources"),
    api.GET("/api/v1/booking/prices"),
  ]);
  if (resources.response.status === 403 || prices.response.status === 403) {
    return <p className="text-muted">{noPermission}</p>;
  }
  if (resources.error || prices.error || !resources.data || !prices.data) {
    throw new Error("Không tải được dữ liệu sân");
  }

  const weekdayPrice: Record<string, number> = {};
  for (const p of prices.data.prices) {
    if (p.day_type === "weekday" && p.band === "offpeak") weekdayPrice[p.resource_type_code] = p.price_per_hour;
  }

  // Đầu trang + tab nằm trong CourtsTable (nút "Thêm sân" mở popup phía client)
  return (
    <CourtsTable
      resources={resources.data.items}
      types={resources.data.resource_types}
      weekdayPrice={weekdayPrice}
      canDelete={can(perms, "booking.resources.delete")}
      t={courts}
    />
  );
}
