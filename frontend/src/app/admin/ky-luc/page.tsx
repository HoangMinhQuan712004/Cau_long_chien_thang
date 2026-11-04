import type { Metadata } from "next";
import { Suspense } from "react";
import { AdminRecordsScreen } from "@/components/records/admin-records-screen";
import { getAdminSession } from "@/lib/api/server";

// Chỉ Admin (nhân viên → thông báo; quyền thật do backend kiểm). Layout admin đã đặt noindex.
export const metadata: Metadata = { title: "Kỷ lục & video" };

export default function AdminRecordsPage() {
  return (
    <Suspense fallback={<p className="text-muted">Đang tải…</p>}>
      <Loader />
    </Suspense>
  );
}

async function Loader() {
  const session = await getAdminSession();
  if (!session.ok || session.session.account.kind !== "admin") return <p className="text-muted">Chỉ chủ sân mới xem được mục này.</p>;
  return <AdminRecordsScreen />;
}
