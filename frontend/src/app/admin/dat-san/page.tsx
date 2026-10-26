import type { Metadata } from "next";
import { Suspense } from "react";
import { CalendarScreen } from "@/components/booking-engine/calendar-screen";
import type { Calendar } from "@/components/booking-engine/types";
import { authedGetJson, getCurrentUser } from "@/lib/api/server";
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
  const sp = await searchParams;
  const date = typeof sp.date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(sp.date) ? sp.date : todayVn();
  const [user, calendar] = await Promise.all([getCurrentUser(), authedGetJson<Calendar>("/api/v1/booking/calendar", { date })]);

  if (!calendar.ok) {
    if (calendar.status === 403) return <p className="text-muted">Bạn không có quyền xem mục này.</p>;
    throw new Error("Không tải được lịch đặt sân");
  }
  return <CalendarScreen initial={calendar.data} role={user?.role === "admin" ? "admin" : "staff"} />;
}
