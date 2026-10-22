import type { Metadata } from "next";
import { Suspense } from "react";
import { BookingAction } from "@/components/booking/booking-action";
import { StatusBadge } from "@/components/booking/status-badge";
import { authedApi, getCourts } from "@/lib/api/server";
import { formatTime, formatVnd, todayVn } from "@/lib/format";

export const metadata: Metadata = { title: "Lịch đặt sân" };

export default function AdminBookingsPage({ searchParams }: PageProps<"/admin">) {
  return (
    <Suspense fallback={<p className="text-muted">Đang tải lịch…</p>}>
      <Bookings searchParams={searchParams} />
    </Suspense>
  );
}

async function Bookings({ searchParams }: Pick<PageProps<"/admin">, "searchParams">) {
  const api = await authedApi();
  const sp = await searchParams;
  const date = typeof sp.date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(sp.date) ? sp.date : todayVn();

  const [{ data: bookings = [], error }, courts] = await Promise.all([
    api.GET("/api/v1/admin/bookings", { params: { query: { date } } }),
    getCourts(),
  ]);
  if (error) throw new Error("Không tải được danh sách đặt sân");

  const courtName = new Map(courts.map((c) => [c.id, c.name]));
  const active = bookings.filter((b) => b.status === "pending" || b.status === "confirmed");
  const revenue = bookings
    .filter((b) => b.status === "confirmed" || b.status === "completed")
    .reduce((sum, b) => sum + b.total_amount, 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h1 className="text-2xl font-bold">Lịch đặt sân</h1>
        <form className="flex items-center gap-2">
          <input
            type="date"
            name="date"
            defaultValue={date}
            aria-label="Ngày"
            className="rounded-md border border-border bg-surface px-3 py-2"
          />
          <button className="rounded-md border border-border px-3 py-2">Xem</button>
        </form>
      </div>

      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Stat label="Đơn đang hoạt động" value={String(active.length)} />
        <Stat
          label="Chờ thanh toán"
          value={String(bookings.filter((b) => b.status === "pending").length)}
        />
        <Stat label="Doanh thu đã xác nhận" value={formatVnd(revenue)} />
      </dl>

      {!bookings.length ? (
        <p className="text-muted">Không có đơn nào trong ngày.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border">
              <tr>
                <th className="p-3">Mã</th>
                <th className="p-3">Khách</th>
                <th className="p-3">Sân & giờ</th>
                <th className="p-3 text-right">Tiền</th>
                <th className="p-3">Trạng thái</th>
                <th className="p-3" />
              </tr>
            </thead>
            <tbody>
              {bookings.map((b) => (
                <tr key={b.id} className="border-b border-border align-top last:border-0">
                  <td className="p-3 font-mono">{b.code}</td>
                  <td className="p-3">
                    {b.customer_name}
                    {b.customer_phone && (
                      <span className="block text-muted">{b.customer_phone}</span>
                    )}
                  </td>
                  <td className="p-3">
                    {b.slots.map((s) => (
                      <span key={`${s.court_id}-${s.start}`} className="block">
                        {courtName.get(s.court_id) ?? `Sân #${s.court_id}`}: {formatTime(s.start)}–
                        {formatTime(s.end)}
                      </span>
                    ))}
                  </td>
                  <td className="p-3 text-right">{formatVnd(b.total_amount)}</td>
                  <td className="p-3">
                    <StatusBadge status={b.status} />
                  </td>
                  <td className="p-3">
                    <div className="flex justify-end gap-2">
                      {b.status === "pending" && <BookingAction id={b.id} action="pay-cash" />}
                      {b.status === "pending" && <BookingAction id={b.id} action="confirm" />}
                      {(b.status === "pending" || b.status === "confirmed") && (
                        <BookingAction id={b.id} action="cancel" />
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="mt-1 text-xl font-semibold">{value}</dd>
    </div>
  );
}
