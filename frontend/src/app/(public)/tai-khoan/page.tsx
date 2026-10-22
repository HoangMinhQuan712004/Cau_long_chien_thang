import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { BookingAction } from "@/components/booking/booking-action";
import { StatusBadge } from "@/components/booking/status-badge";
import { LogoutButton } from "@/components/logout-button";
import { authedApi, getCurrentUser } from "@/lib/api/server";
import { formatDate, formatTime, formatVnd } from "@/lib/format";

export const metadata: Metadata = {
  title: "Tài khoản của tôi",
  robots: { index: false },
};

export default function AccountPage() {
  return (
    <Suspense fallback={<p className="text-muted">Đang tải…</p>}>
      <Account />
    </Suspense>
  );
}

async function Account() {
  const user = await getCurrentUser();
  if (!user) redirect("/dang-nhap?next=/tai-khoan");

  const api = await authedApi();
  const { data: bookings = [], error } = await api.GET("/api/v1/bookings/me");
  if (error) throw new Error("Không tải được lịch sử đặt sân");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Xin chào, {user.full_name}</h1>
          <p className="text-sm text-muted">{user.email}</p>
        </div>
        <div className="flex items-center gap-4">
          {user.role !== "customer" && (
            <Link href="/admin" className="text-sm text-primary">
              Trang quản lý →
            </Link>
          )}
          <LogoutButton />
        </div>
      </div>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Lịch sử đặt sân</h2>
        {!bookings.length ? (
          <p className="text-muted">
            Bạn chưa đặt sân nào.{" "}
            <Link href="/dat-san" className="text-primary">
              Đặt ngay
            </Link>
          </p>
        ) : (
          <ul className="space-y-3">
            {bookings.map((b) => (
              <li key={b.id} className="rounded-lg border border-border bg-surface p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-mono text-sm">{b.code}</p>
                  <StatusBadge status={b.status} />
                </div>
                <ul className="mt-2 text-sm">
                  {b.slots.map((s) => (
                    <li key={`${s.court_id}-${s.start}`}>
                      Sân #{s.court_id} · {formatDate(s.start)} · {formatTime(s.start)}–
                      {formatTime(s.end)}
                    </li>
                  ))}
                </ul>
                <div className="mt-2 flex items-center justify-between">
                  <p className="font-semibold">{formatVnd(b.total_amount)}</p>
                  {b.status === "pending" && <BookingAction id={b.id} action="cancel" />}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
