import Link from "next/link";
import { Avatar } from "@/components/member-area/avatar";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/cn";
import { formatDayMonth, vnDate } from "@/lib/format";

// "Hạng của tôi · Tháng n" + Top 3 của Tổng quan: thẻ vàng nhạt (máy tính: cột phải, dính khi cuộn).

type Ranking = components["schemas"]["Overview"]["ranking"];

const MEDAL = ["bg-medal-gold", "bg-medal-silver", "bg-medal-bronze"];

export function RankPanel({ ranking, month }: { ranking: Ranking; month: number }) {
  const { me, top3, total_records } = ranking;
  const bar = me ? (me.gap_to_top10 === null || !me.top10_kmh ? 100 : Math.min(100, Math.round((me.speed_kmh / me.top10_kmh) * 100))) : 0;
  const inTop3 = top3.some((r) => r.is_me);
  return (
    <section className="rounded-2xl border border-accent/45 bg-accent-soft/45 p-4 shadow-card sm:p-5" aria-labelledby="rank-title">
      <div className="flex items-center justify-between gap-3">
        <h2 id="rank-title" className="text-xs font-bold tracking-wider text-accent-fg">
          HẠNG CỦA TÔI · THÁNG {month}
        </h2>
        <Link href="/hoi-vien/bang-xep-hang" className="shrink-0 rounded-sm text-sm font-semibold text-primary hover:underline focus-ring">
          Bảng xếp hạng ›
        </Link>
      </div>

      {top3.length === 0 && !me ? (
        <p className="py-6 text-sm text-muted">Chưa có số đo tốc độ trong tháng này</p>
      ) : (
        <>
          {me ? (
            <div className="mt-2">
              <div className="flex items-end justify-between gap-3">
                <p>
                  <b className="text-5xl font-extrabold tracking-tight tabular-nums">#{me.rank}</b> <span className="text-sm text-muted">/ {total_records} cú đập</span>
                </p>
                <p className="text-xl font-bold tabular-nums">{me.speed_kmh} km/h</p>
              </div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-border" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={bar} aria-label="Tiến độ tới top 10">
                <div className="h-full rounded-full bg-linear-to-r from-primary-hover to-accent" style={{ width: `${bar}%` }} />
              </div>
              {me.gap_to_top10 !== null ? (
                <p className="mt-1.5 text-xs text-muted">
                  Cách top 10: <b className="text-foreground">+{me.gap_to_top10} km/h</b>
                  {me.top10_kmh ? ` (hạng 10 đạt ${me.top10_kmh} km/h)` : ""}
                </p>
              ) : null}
            </div>
          ) : (
            <p className="mt-3 text-sm font-medium">Bạn chưa có số đo trong tháng này</p>
          )}

          {top3.length > 0 ? (
            <>
              <h3 className="mt-5 text-xs font-bold tracking-wider text-accent-fg">TOP 3 THÁNG</h3>
              <ol className="mt-1 divide-y divide-accent/25">
                {top3.map((r, i) => (
                  <li key={r.rank} className="flex items-center gap-2.5 py-2.5">
                    <span aria-label={`Hạng ${r.rank}`} className={cn("grid size-6 shrink-0 place-items-center rounded-full text-xs font-bold text-medal-fg", MEDAL[i] ?? "bg-border")}>
                      {r.rank}
                    </span>
                    <Avatar url={r.avatar_url} name={r.display_name} size={30} />
                    <span className="min-w-0 flex-1 text-sm font-medium">
                      <span className="flex min-w-0 items-center gap-1.5">
                        <span className="truncate">{r.display_name}</span>
                        {r.is_me ? <span className="shrink-0 rounded-full bg-primary-softer px-2 py-0.5 text-xs font-semibold text-primary">Bạn</span> : null}
                      </span>
                      <span className="block truncate text-xs font-normal text-muted tabular-nums">
                        {formatDayMonth(vnDate(r.measured_at))}
                        {r.resource_name ? ` · ${r.resource_name}` : ""}
                      </span>
                    </span>
                    <span className="text-sm font-bold tabular-nums">{r.speed_kmh} km/h</span>
                  </li>
                ))}
                {me && !inTop3 ? (
                  <li className="flex items-center gap-2.5 py-2.5">
                    <span className="grid size-6 shrink-0 place-items-center text-xs font-semibold text-muted">{me.rank}</span>
                    <span className="min-w-0 flex-1 truncate text-sm font-medium">
                      <span className="rounded-full bg-primary-softer px-2 py-0.5 text-xs font-semibold text-primary">Bạn</span>
                    </span>
                    <span className="text-sm font-bold tabular-nums">{me.speed_kmh} km/h</span>
                  </li>
                ) : null}
              </ol>
            </>
          ) : null}
        </>
      )}
    </section>
  );
}
