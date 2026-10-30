import { type Column, DataTable } from "@/components/ui/data-table";
import type { Dictionary } from "@/i18n/dictionaries";
import type { MemberDetail } from "@/lib/api/server";
import { formatDayMonthYear, formatVnd, hhmm } from "@/lib/format";

type Booking = MemberDetail["recent_bookings"][number];

/** Lượt đặt gần nhất trong ngăn chi tiết: chọn bảng hay thẻ theo bề rộng ngăn (kéo dãn được), không theo màn hình. */
export function MemberRecentBookings({ bookings, t }: { bookings: readonly Booking[]; t: Dictionary["members"]["drawer"] }) {
  const columns: Column<Booking>[] = [
    { key: "code", header: t.cols.code, className: "whitespace-nowrap", card: "subtitle", cell: (b) => b.order_code ?? b.code },
    // Ngày và giờ tách cột; thẻ điện thoại ghép lại ở dòng đầu "30/10/2026 13:00–14:00"
    { key: "date", header: t.cols.date, className: "whitespace-nowrap tabular-nums", card: "title", cell: (b) => formatDayMonthYear(b.play_date) },
    {
      key: "time",
      header: t.cols.time,
      className: "whitespace-nowrap tabular-nums",
      card: "title",
      cell: (b) => `${hhmm(b.start_time)}–${hhmm(b.end_time)}`,
    },
    { key: "court", header: t.cols.court, card: "meta", cell: (b) => b.resource_name },
    {
      key: "amount",
      header: t.cols.amount,
      align: "right",
      className: "whitespace-nowrap tabular-nums",
      card: "meta",
      cell: (b) => formatVnd(b.amount),
    },
  ];

  return (
    <section className="flex flex-col gap-2 sm:gap-3">
      <h3 className="text-sm font-semibold sm:text-base">
        {t.historyTitle}
      </h3>
      <DataTable
        caption={t.historyTitle}
        columns={columns}
        rows={bookings}
        rowKey={(b) => b.code}
        layout="container"
        empty={t.historyEmpty}
      />
    </section>
  );
}
