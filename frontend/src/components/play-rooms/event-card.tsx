import Link from "next/link";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/cn";
import { formatLongDate, formatVnd } from "@/lib/format";
import { hourRange } from "./utils";

// Thẻ "Sự kiện sắp tới" (T-045): dùng ở Tổng quan và tab "Sự kiện" của Danh sách sân.
// Nút "Đặt vé" mở popup mua vé T-023 qua `/hoi-vien/dat-san?date&event`; không đặt được thì nút mờ kèm lý do (`reason`).

export type EventCardData = components["schemas"]["EventCard"];

/** Lý do không đặt online được, theo `reason` của BE. */
const REASON: Record<NonNullable<EventCardData["reason"]>, string> = {
  full: "Đã đủ chỗ",
  free: "Đăng ký tại quầy",
  online_off: "Đặt online đang tạm ngưng",
};

export const eventHref = (e: Pick<EventCardData, "play_date" | "code">) => `/hoi-vien/dat-san?date=${e.play_date}&event=${e.code}`;

export function EventCard({ e, className }: { e: EventCardData; className?: string }) {
  const reason = e.reason ? REASON[e.reason] : null;
  const free = e.reason === "free";
  return (
    <article className={cn("flex h-full flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-card", className)}>
      <div className="flex items-center justify-between gap-2 bg-blk-session px-4 py-2 text-blk-session-fg">
        <span className="text-xs font-bold">Sự kiện</span>
        {e.my_ticket_count > 0 ? <span className="rounded-full bg-surface px-2.5 py-0.5 text-xs font-bold">Bạn có {e.my_ticket_count} vé</span> : null}
      </div>
      <div className="flex flex-1 flex-col gap-1 p-4">
        <h3 className="text-base leading-snug font-bold break-words">{e.name}</h3>
        <p className="text-sm font-medium tabular-nums">
          {formatLongDate(e.play_date)} · {hourRange(e.start_at, e.end_at)}
        </p>
        <p className="text-sm text-muted">{e.resource_names.join(", ")}</p>
        <div className="mt-1 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-sm">
          <span className="font-semibold">{free ? "Miễn phí" : formatVnd(e.ticket_price)}</span>
          <span className={cn("tabular-nums", e.remaining === 0 ? "font-semibold text-danger" : "text-muted")} aria-label={`Còn ${e.remaining} trên ${e.capacity} chỗ`}>
            Còn {e.remaining}/{e.capacity} chỗ
          </span>
        </div>
        <div className="mt-auto pt-3">
          {e.can_buy ? (
            <Link href={eventHref(e)} className="inline-flex h-11 w-full items-center justify-center rounded-lg bg-cta px-4 text-sm font-bold tracking-wide text-cta-fg uppercase hover:bg-cta-hover focus-ring">
              Đặt vé
            </Link>
          ) : free ? (
            <p className="rounded-lg bg-background px-3 py-2.5 text-center text-sm font-medium text-muted">{reason}</p>
          ) : (
            <>
              <button type="button" disabled aria-describedby={`ev-${e.code}-why`} className="h-11 w-full rounded-lg bg-cta px-4 text-sm font-bold tracking-wide text-cta-fg uppercase opacity-45">
                Đặt vé
              </button>
              <p id={`ev-${e.code}-why`} className="mt-1.5 text-center text-xs text-muted">
                {reason}
              </p>
            </>
          )}
        </div>
      </div>
    </article>
  );
}
