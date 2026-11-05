import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { STATUS_LABEL } from "@/components/booking-engine/ui";
import type { PaymentStatus } from "@/components/booking-engine/types";
import { formatDayMonth, formatDayMonthYear, formatNumber } from "@/lib/format";
import type { CourtDetail } from "./court-drawer";
import { bandsOf, t5 } from "./court-form-logic";

// Các mục chỉ đọc của ngăn chi tiết sân: thông tin + giờ mở cửa, bảng giá đang áp (chỉ xem), lịch sắp tới.

export const SECTION = "flex flex-col gap-3 py-5 first:pt-0";
export const SECTION_TITLE = "text-label font-semibold tracking-wide text-muted uppercase";
const LINK = "inline-flex min-h-11 items-center self-start text-sm font-semibold text-primary hover:underline focus-ring sm:min-h-0";

const DAY_TYPES = [
  { key: "weekday", label: "Ngày thường" },
  { key: "weekend", label: "Cuối tuần" },
  { key: "holiday", label: "Lễ, Tết" },
] as const;

export function CourtOverview({ detail, typeName }: { detail: CourtDetail; typeName?: string }) {
  const r = detail.resource;
  const s = r.schedule;
  const price = (day: string, band: string) => detail.prices.find((p) => p.day_type === day && p.band === band)?.price_per_hour;

  return (
    <>
      <section aria-labelledby="court-info" className={SECTION}>
        <div className="flex flex-wrap items-center gap-2">
          <h3 id="court-info" className="sr-only">Thông tin sân</h3>
          <span className="text-sm text-muted">{typeName ?? r.resource_type_name}</span>
          <Badge variant={r.is_active ? "success" : "neutral"}>{r.is_active ? "Hoạt động" : "Ngừng hoạt động"}</Badge>
        </div>
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
          <dt className="text-muted">Giờ mở cửa</dt>
          <dd className="font-semibold tabular-nums">{s ? `${t5(s.open_time)} – ${t5(s.close_time)}` : "—"}</dd>
          <dt className="text-muted">Cao điểm</dt>
          <dd className="tabular-nums">{s && s.peak_bands.length ? bandsOf(s).map((b) => `${b[0]}–${b[1]}`).join(", ") : "Không có"}</dd>
          {r.pending_schedule ? (
            <>
              <dt className="text-muted">Giờ mới</dt>
              <dd className="tabular-nums">
                {t5(r.pending_schedule.open_time)} – {t5(r.pending_schedule.close_time)} từ {formatDayMonthYear(r.pending_schedule.effective_from)}
              </dd>
            </>
          ) : null}
        </dl>
      </section>

      <section aria-labelledby="court-prices" className={SECTION}>
        <h3 id="court-prices" className={SECTION_TITLE}>Bảng giá đang áp (₫/giờ)</h3>
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted">
            <tr>
              <th className="py-1 font-medium" />
              <th className="py-1 text-right font-medium">Thấp điểm</th>
              <th className="py-1 text-right font-medium">Cao điểm</th>
            </tr>
          </thead>
          <tbody>
            {DAY_TYPES.map((d) => (
              <tr key={d.key} className="border-t border-border/60">
                <th scope="row" className="py-2 text-left font-normal text-muted">{d.label}</th>
                {(["offpeak", "peak"] as const).map((b) => {
                  const v = price(d.key, b);
                  return <td key={b} className="py-2 text-right font-semibold tabular-nums">{v != null ? formatNumber(v) : "—"}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-ui text-muted">Giá theo loại sân, dùng chung cho mọi sân cùng loại.</p>
        <Link href="/admin/san/bang-gia" className={LINK}>Sửa ở Bảng giá ›</Link>
      </section>

      <section aria-labelledby="court-upcoming" className={SECTION}>
        <h3 id="court-upcoming" className={SECTION_TITLE}>Lịch sắp tới</h3>
        {detail.upcoming.length ? (
          <ul className="flex flex-col divide-y divide-border/60">
            {detail.upcoming.map((u) => (
              <li key={u.code} className="flex items-start justify-between gap-3 py-2.5">
                <span className="flex min-w-0 flex-col">
                  <span className="text-sm font-semibold tabular-nums">
                    {formatDayMonth(u.play_date)} · {t5(u.start_time)}–{t5(u.end_time)}
                  </span>
                  <span className="text-ui text-muted wrap-anywhere">{u.kind === "session" ? `Sự kiện · ${u.title}` : u.title}</span>
                </span>
                {u.payment_status ? (
                  <Badge variant={u.payment_status === "paid" ? "success" : u.payment_status === "unpaid" ? "warning" : "neutral"}>
                    {STATUS_LABEL[u.payment_status as PaymentStatus] ?? u.payment_status}
                  </Badge>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">Chưa có lịch đặt sắp tới.</p>
        )}
        <Link href={detail.upcoming[0] ? `/admin/dat-san?date=${detail.upcoming[0].play_date}` : "/admin/dat-san"} className={LINK}>Xem trên lịch ›</Link>
      </section>
    </>
  );
}
