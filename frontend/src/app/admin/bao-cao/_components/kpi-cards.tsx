import { Card } from "@/components/ui/card";
import { InfoTip } from "@/components/ui/info-tip";
import { Skeleton } from "@/components/ui/skeleton";
import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";
import { count, fill, money } from "./report-format";
import type { ReportOverview } from "@/lib/api/server";

type T = Dictionary["report"]["kpi"];
type Props = { data: ReportOverview | null; t: T };

/** 3 thẻ chỉ số: Tổng doanh thu, Số lượt đặt, Hội viên mới; (i) giải thích cách tính (BR-012). Chưa có số ⇒ khung chờ. */
export function KpiCards({ data, t }: Props) {
  const cards = [
    {
      key: "revenue",
      text: t.revenue,
      value: data ? money(data.revenue.current) : null,
      tip: t.revenue.tip,
    },
    {
      key: "bookings",
      text: t.bookings,
      value: data ? count(data.bookings.current) : null,
      // Số vé xé vé của kỳ nằm trong (i) (chưa có số ⇒ câu gốc)
      tip: data ? `${t.bookings.tip} ${fill(t.bookings.tickets, { n: count(data.bookings.tickets) })}` : t.bookings.tip,
    },
    {
      key: "members",
      text: t.members,
      value: data ? count(data.new_members.current) : null,
      tip: t.members.tip,
    },
  ];

  return (
    // Điện thoại: Tổng doanh thu rộng hết hàng, 2 thẻ còn lại 2 cột; từ md 3 thẻ một hàng
    <div className="grid grid-cols-2 gap-2.5 sm:gap-3 md:grid-cols-3 lg:gap-4">
      {cards.map(({ key, text, value, tip }) => (
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
          {value !== null ? (
            <span className={cn(`
              text-xl font-extrabold tracking-tight tabular-nums
              sm:text-2xl
              xl:text-3xl
            `)}>{value}</span>
          ) : (
            <Skeleton className="my-1 h-6 w-32 sm:h-7 sm:w-40 xl:h-8" />
          )}
        </Card>
      ))}
    </div>
  );
}
