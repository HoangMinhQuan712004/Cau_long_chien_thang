import type { Metadata } from "next";
import { Suspense } from "react";
import { CalendarScreen } from "@/components/booking-engine/calendar-screen";
import type { Calendar } from "@/components/booking-engine/types";
import { authedGetJson, getAdminSession } from "@/lib/api/server";
import { todayVn } from "@/lib/format";

export const metadata: Metadata = { title: "Đặt sân" };

export default function BookingCalendarPage({ searchParams }: PageProps<"/admin/dat-san">) {
  return (
    <Suspense fallback={<p className="text-muted">Đang tải lịch…</p>}>
      <CalendarLoader searchParams={searchParams} />
    </Suspense>
  );
}

async function CalendarLoader({ searchParams }: Pick<PageProps<"/admin/dat-san">, "searchParams">) {
  // Đọc cookie (dữ liệu theo người dùng) trước khi dùng giờ hiện tại, để Next coi đây là nội dung động.
  const session = await getAdminSession();
  const sp = await searchParams;
  const date = typeof sp.date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(sp.date) ? sp.date : todayVn();
  const calendar = await authedGetJson<Calendar>("/api/v1/booking/calendar", { date });

  if (!calendar.ok) {
    if (calendar.status === 403) return <p className="text-muted">Bạn không có quyền xem mục này.</p>;
    throw new Error("Không tải được lịch đặt sân");
  }
  return <CalendarScreen initial={calendar.data} role={session.ok && session.session.account.kind === "admin" ? "admin" : "staff"} />;
}
