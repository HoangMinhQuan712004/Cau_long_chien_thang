import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";
import { OrdersScreen } from "@/components/booking-engine/orders-screen";
import { getAdminSession } from "@/lib/api/server";
import { todayVn } from "@/lib/format";

// Chỉ Admin (nhân viên → thông báo; quyền thật do backend kiểm). Layout admin đã đặt noindex.
export const metadata: Metadata = { title: "Đơn đặt sân" };

export default function OrdersPage() {
  return (
    <Suspense fallback={<p className="text-muted">Đang tải…</p>}>
      <Loader />
    </Suspense>
  );
}

async function Loader() {
  const session = await getAdminSession(); // đọc cookie trước khi dùng giờ hiện tại
  await connection();
  if (!session.ok || session.session.account.kind !== "admin") return <p className="text-muted">Chỉ chủ sân mới xem được mục này.</p>;
  return <OrdersScreen today={todayVn()} />;
}
