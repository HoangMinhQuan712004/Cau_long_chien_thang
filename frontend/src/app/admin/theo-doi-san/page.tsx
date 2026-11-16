import type { Metadata } from "next";
import { Suspense } from "react";
import { MonitorScreen } from "@/components/play-rooms/monitor/monitor-screen";
import { Alert } from "@/components/ui/alert";
import { getDictionary } from "@/i18n/dictionaries";
import { adminPerms } from "@/lib/api/server";
import { can } from "../_components/forbidden";

// Theo quyền play_rooms.monitor (thiếu ⇒ dòng báo; backend vẫn kiểm: 403). Layout admin đã đặt noindex.
export const metadata: Metadata = { title: "Theo dõi sân", robots: { index: false } };

export default function CourtMonitorPage() {
  return (
    <Suspense fallback={<p className="text-muted">Đang tải…</p>}>
      <Loader />
    </Suspense>
  );
}

async function Loader() {
  const [perms, { adminNav }] = await Promise.all([adminPerms(), getDictionary()]); // đọc cookie trước khi dùng giờ hiện tại
  if (!can(perms, "play_rooms.monitor")) return <Alert variant="error">{adminNav.forbidden}</Alert>;
  return <MonitorScreen />;
}
