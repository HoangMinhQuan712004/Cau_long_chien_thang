import { Card } from "@/components/ui/card";
import { InfoTip } from "@/components/ui/info-tip";
import { Skeleton } from "@/components/ui/skeleton";
import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";
import { count, decimal1, fill, money, round1 } from "./report-format";
import type { ReportOverview } from "@/lib/api/server";

type T = Dictionary["report"]["kpi"];
type Trend = "up" | "down" | "flat";

const TREND_CLASS: Record<Trend, string> = { up: "text-primary", down: "text-danger", flat: "text-muted" };
const ARROW: Record<Trend, string> = { up: "↑", down: "↓", flat: "" };

/**
 * Dòng so sánh với kỳ trước (BR-009): tiền / lượt ⇒ % thay đổi; hội viên ⇒ số chênh.
 * Kỳ trước 0 mà kỳ này > 0 (chỉ % ) ⇒ "Kỳ trước chưa có số liệu"; bằng nhau / tròn ra 0,0% ⇒ "Không đổi".
 * `head` = "↓ −1,8%" (đậm, có màu), `text` = "so với 7 ngày trước", `prev` = số kỳ trước (không ngắt giữa) –
 * tách để thẻ hẹp xuống dòng đúng chỗ.
 */
function compare(cur: number, prev: number, days: number, unit: (n: number) => string, isDelta: boolean, t: T) {
  const vars = { n: days };
  const before = `(${unit(prev)})`;
  if (!isDelta && prev === 0 && cur > 0) return { trend: "flat" as Trend, head: null, text: t.noPrevious, prev: null };
  const change = isDelta ? cur - prev : prev === 0 ? 0 : round1(((cur - prev) / prev) * 100);
  if (change === 0) return { trend: "flat" as Trend, head: null, text: fill(t.same, vars), prev: before };
  const trend: Trend = change > 0 ? "up" : "down";
  const abs = isDelta ? count(Math.abs(change)) : `${decimal1(Math.abs(change))}%`;
  return { trend, head: `${ARROW[trend]} ${change > 0 ? "+" : "−"}${abs}`, text: fill(t.compare, vars), prev: before };
}

type Props = { data: ReportOverview | null; t: T };

/** 3 thẻ chỉ số: Tổng doanh thu, Số lượt đặt, Hội viên mới; (i) giải thích cách tính (BR-012). Chưa có số ⇒ khung chờ. */
export function KpiCards({ data, t }: Props) {
  const days = data?.period.days ?? 0;
  const cards = [
    {
      key: "revenue",
      text: t.revenue,
      value: data ? money(data.revenue.current) : null,
      cmp: data ? compare(data.revenue.current, data.revenue.previous, days, money, false, t) : null,
      tip: t.revenue.tip,
    },
    {
      key: "bookings",
      text: t.bookings,
      value: data ? count(data.bookings.current) : null,
      cmp: data
        ? compare(data.bookings.current, data.bookings.previous, days, (n) => fill(t.bookings.unit, { n: count(n) }), false, t)
        : null,
      // Số vé xé vé của kỳ nằm trong (i) (chưa có số ⇒ câu gốc)
      tip: data ? `${t.bookings.tip} ${fill(t.bookings.tickets, { n: count(data.bookings.tickets) })}` : t.bookings.tip,
    },
    {
      key: "members",
      text: t.members,
      value: data ? count(data.new_members.current) : null,
      cmp: data
        ? compare(data.new_members.current, data.new_members.previous, days, (n) => fill(t.members.unit, { n: count(n) }), true, t)
        : null,
      tip: t.members.tip,
    },
  ];

  return (
    // Điện thoại: Tổng doanh thu rộng hết hàng, 2 thẻ còn lại 2 cột; từ md 3 thẻ một hàng
    <div className="grid grid-cols-2 gap-2.5 sm:gap-3 md:grid-cols-3 lg:gap-4">
      {cards.map(({ key, text, value, cmp, tip }) => (
        <Card
          key={key}
          className={cn(
            "flex min-w-0 flex-col gap-1 px-3 py-2.5 sm:gap-1.5 sm:px-4 sm:py-3.5 lg:px-4.5 lg:py-4",
            key === "revenue" && "col-span-2 md:col-span-1",
          )}
        >
          <span className="flex items-center gap-1 text-xs font-semibold text-muted sm:text-ui">
            {text.label}
            <InfoTip text={tip} label={t.explain} />
          </span>
          {value !== null && cmp ? (
            <>
              <span className={cn(`
                text-xl font-extrabold tracking-tight tabular-nums
                sm:text-2xl
                xl:text-3xl
              `)}>{value}</span>
              {/* Thẻ hẹp: "↓ −1,8%" một dòng, phần "so với…" xuống dòng nguyên cụm */}
              <span className="flex flex-wrap gap-x-1 text-xs tabular-nums sm:text-ui">
                {cmp.head ? <b className={cn("font-semibold whitespace-nowrap", TREND_CLASS[cmp.trend])}>{cmp.head}</b> : null}
                <span className={cn("text-pretty", cmp.head ? "text-muted" : TREND_CLASS[cmp.trend])}>
                  {cmp.text}
                  {cmp.prev ? <>{" "}<span className="whitespace-nowrap">{cmp.prev}</span></> : null}
                </span>
              </span>
            </>
          ) : (
            <>
              <Skeleton className="my-1 h-6 w-32 sm:h-7 sm:w-40 xl:h-8" />
              <Skeleton className="h-4 w-full max-w-52" />
            </>
          )}
        </Card>
      ))}
    </div>
  );
}
