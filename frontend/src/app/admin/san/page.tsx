import type { Metadata } from "next";
import { Suspense } from "react";
import { PriceTable } from "@/components/price-table";
import { authedApi } from "@/lib/api/server";

export const metadata: Metadata = { title: "Sân & bảng giá" };

export default function CourtsAdminPage() {
  return (
    <Suspense fallback={<p className="text-muted">Đang tải…</p>}>
      <Courts />
    </Suspense>
  );
}

async function Courts() {
  const api = await authedApi();
  // Dùng API admin để thấy cả sân / giá đang tạm ngưng
  const [courts, rules] = await Promise.all([
    api.GET("/api/v1/admin/courts"),
    api.GET("/api/v1/admin/price-rules"),
  ]);
  if (courts.response.status === 403) {
    return <p className="text-muted">Chỉ chủ sân mới xem được mục này.</p>;
  }
  if (courts.error || rules.error) throw new Error("Không tải được dữ liệu sân");

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <h1 className="text-2xl font-bold">Danh sách sân</h1>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {courts.data.map((c) => (
            <li key={c.id} className="rounded-lg border border-border bg-surface p-4">
              <p className="font-semibold">{c.name}</p>
              <p className="text-sm text-muted">{c.surface ?? "—"}</p>
              <p className={`mt-1 text-xs ${c.is_active ? "text-success" : "text-danger"}`}>
                {c.is_active ? "Đang hoạt động" : "Tạm ngưng"}
              </p>
            </li>
          ))}
        </ul>
        {/* TODO: form thêm / sửa sân -> POST/PUT /api/v1/admin/courts */}
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Bảng giá</h2>
        <PriceTable rules={rules.data} />
        {/* TODO: form quản lý bảng giá -> /api/v1/admin/price-rules */}
      </section>
    </div>
  );
}
