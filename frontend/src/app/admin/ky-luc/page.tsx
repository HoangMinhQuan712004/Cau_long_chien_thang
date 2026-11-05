import type { Metadata } from "next";
import { Suspense } from "react";
import { AdminRecordsScreen } from "@/components/records/admin-records-screen";
import { getDictionary } from "@/i18n/dictionaries";
import { adminPerms } from "@/lib/api/server";
import { can } from "../_components/forbidden";

// Theo quyền records.video.manage (thiếu ⇒ dòng báo không có quyền; backend vẫn kiểm). Layout admin đã đặt noindex.
export const metadata: Metadata = { title: "Kỷ lục & video" };

export default function AdminRecordsPage() {
  return (
    <Suspense fallback={<p className="text-muted">Đang tải…</p>}>
      <Loader />
    </Suspense>
  );
}

async function Loader() {
  const [perms, { adminNav }] = await Promise.all([adminPerms(), getDictionary()]); // đọc cookie trước khi dùng giờ hiện tại
  if (!can(perms, "records.video.manage")) return <p className="text-muted">{adminNav.noPermission}</p>;
  return <AdminRecordsScreen />;
}
