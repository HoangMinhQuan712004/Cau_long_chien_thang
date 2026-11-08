import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";
import { OrdersScreen } from "@/components/booking-engine/orders-screen";
import { getDictionary } from "@/i18n/dictionaries";
import { adminPerms } from "@/lib/api/server";
import { can } from "../_components/forbidden";
import { todayVn } from "@/lib/format";

// Theo quyền booking.orders.view (thiếu ⇒ dòng báo không có quyền; backend vẫn kiểm). Layout admin đã đặt noindex.
export const metadata: Metadata = { title: "Đơn đặt sân" };

export default function OrdersPage({ searchParams }: PageProps<"/admin/don-dat-san">) {
  return (
    <Suspense fallback={<p className="text-muted">Đang tải…</p>}>
      <Loader searchParams={searchParams} />
    </Suspense>
  );
}

async function Loader({ searchParams }: Pick<PageProps<"/admin/don-dat-san">, "searchParams">) {
  const [perms, { adminNav }] = await Promise.all([adminPerms(), getDictionary()]); // đọc cookie trước khi dùng giờ hiện tại
  if (!can(perms, "booking.orders.view")) return <p className="text-muted">{adminNav.noPermission}</p>;
  await connection();
  // ?q=<mã đơn>: mở từ link mã đơn ở Lịch sử giao dịch (T-057)
  const raw = (await searchParams).q;
  const q = (Array.isArray(raw) ? raw[0] : raw)?.trim().slice(0, 100) ?? "";
  return <OrdersScreen today={todayVn()} initialQ={q} />;
}
