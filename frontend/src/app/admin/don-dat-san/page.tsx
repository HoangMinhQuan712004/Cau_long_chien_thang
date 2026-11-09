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

export default function OrdersPage() {
  return (
    <Suspense fallback={<p className="text-muted">Đang tải…</p>}>
      <Loader />
    </Suspense>
  );
}

async function Loader() {
  const [perms, { adminNav }] = await Promise.all([adminPerms(), getDictionary()]); // đọc cookie trước khi dùng giờ hiện tại
  if (!can(perms, "booking.orders.view")) return <p className="text-muted">{adminNav.noPermission}</p>;
  await connection();
  return <OrdersScreen today={todayVn()} />;
}
