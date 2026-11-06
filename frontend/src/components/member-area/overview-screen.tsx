"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Avatar } from "@/components/member-area/avatar";
import { PageBanner } from "@/components/member-area/page-banner";
import { roomsApi } from "@/components/play-rooms/requests";
import { VideoPlayer } from "@/components/records/video-player";
import type { RoomCard } from "@/components/play-rooms/types";
import { EventCard } from "@/components/play-rooms/event-card";
import { hourRange, joinBlockText, tierRangeText } from "@/components/play-rooms/utils";
import { Button } from "@/components/ui/button";
import { usePolling } from "@/hooks/use-polling";
import { api } from "@/lib/api/client";
import { errorText } from "@/lib/api/write";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/cn";
import { toast } from "@/lib/feedback";
import { formatDayMonth, formatLongDate, vnDate, vnMinutes } from "@/lib/format";

// /hoi-vien – Tổng quan v2 (T-036): banner + 3 thẻ số, Tiếp theo, Phòng đang trống, Hạng của tôi + Top 3, Kỷ lục mới.
// Một lần gọi GET /member-area/overview (kiểu sinh từ schema.d.ts). Khối không có dữ liệu thì ẩn hoặc hiện trạng thái trống.

type Overview = components["schemas"]["Overview"];
type Upcoming = components["schemas"]["UpcomingItem"];

const WEEKDAY = ["CN", "T2", "T3", "T4", "T5", "T6", "T7"];
const shortDay = (iso: string) => {
  const d = vnDate(iso);
  return `${WEEKDAY[new Date(`${d}T00:00:00Z`).getUTCDay()]} ${d.slice(8, 10)}/${d.slice(5, 7)}`;
};
const monthNo = (ym: string | undefined, today: string) => Number((ym ?? today).slice(5, 7));

/** 05–11 sáng, 11–18 chiều, còn lại tối (giờ Việt Nam). */
function greetingOf(nowMs: number): string {
  const hour = vnMinutes(new Date(nowMs).toISOString()) / 60;
  return hour >= 5 && hour < 11 ? "sáng" : hour >= 11 && hour < 18 ? "chiều" : "tối";
}

const ctaCls = "inline-flex h-11 items-center justify-center rounded-lg bg-cta px-6 text-sm font-bold tracking-wide text-cta-fg uppercase hover:bg-cta-hover focus-ring";
const card = "rounded-xl bg-surface p-4 shadow-card sm:p-5";

const ArrowUpRight = ({ className }: { className?: string }) => (
  <svg viewBox="0 0 20 20" className={cn("size-4 shrink-0", className)} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="M6 14 14 6M7 6h7v7" />
  </svg>
);

export function OverviewScreen() {
  const [data, setData] = useState<Overview | null>(null);
  const [failed, setFailed] = useState(false);
  // Mốc lúc tải gần nhất: dùng cho lời chào và "Còn n phút" (không đọc đồng hồ khi render)
  const [nowMs, setNowMs] = useState(0);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const ov = await api.GET("/api/v1/member-area/overview");
      if (ov.response.status === 401) {
        window.location.replace(`/dang-nhap?next=${encodeURIComponent("/hoi-vien")}&ly-do=het-han`);
        return;
      }
      if (ov.data) {
        setData(ov.data);
        setNowMs(Date.now());
        setFailed(false);
      } else setFailed(true);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải lần đầu khi vào trang
    void load();
  }, [load]);
  usePolling(() => void load(), 15000);

  /** "Xin vào" ở khối Phòng đang trống: đúng API xin vào của T-017 (kèm version phòng). */
  async function requestJoin(room: RoomCard) {
    if (busyId !== null) return;
    setBusyId(room.id);
    try {
      const res = await roomsApi.requestJoin(room.id, room.version);
      if (!res.ok) toast(errorText(res.error), undefined, "error");
      else toast("Đã gửi yêu cầu vào phòng", `${room.resource_name} · Host sẽ duyệt`);
    } finally {
      setBusyId(null);
    }
    await load();
  }

  const next = data?.upcoming[0];
  const month = data ? monthNo(data.month, data.today) : 0;
  const stats = data?.month_stats;

  return (
    <>
      <PageBanner
        title={data ? `Chào buổi ${greetingOf(nowMs)}, ${data.greeting_name}` : "Tổng quan"}
        subtitle={data ? `${formatLongDate(data.today)} · Bạn có ${data.today_count} lịch chơi hôm nay` : "Đang tải…"}
        aside={
          <Link href="/hoi-vien/dat-san" className="inline-flex h-11 items-center gap-2 rounded-lg bg-surface px-5 text-sm font-semibold text-primary-hover hover:bg-primary-softer focus-ring max-lg:hidden">
            Đặt sân <ArrowUpRight />
          </Link>
        }
      >
        {data ? (
          <div className="relative mx-auto max-w-6xl px-4 pb-6">
            <div className="-mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-1 sm:mx-0 sm:grid sm:grid-cols-3 sm:overflow-visible sm:px-0">
              <StatCard href="/hoi-vien/lich-su-choi" label="Buổi chơi" month={month} value={stats ? String(stats.sessions) : "—"} unit="buổi" />
              <StatCard href="/hoi-vien/lich-su-choi" label="Trận thắng" month={month} value={stats ? String(stats.wins) : "—"} unit={stats ? `/ ${stats.matches} trận` : ""} />
              <StatCard
                href="/hoi-vien/bang-xep-hang"
                label="Kỷ lục cá nhân"
                month={month}
                value={data.month_record_kmh != null ? String(data.month_record_kmh) : "—"}
                unit={data.month_record_kmh != null ? "km/h" : ""}
                sub={data.month_record_kmh == null && data.record_kmh != null ? `Kỷ lục mọi thời gian: ${data.record_kmh} km/h` : undefined}
              />
            </div>
          </div>
        ) : null}
      </PageBanner>

      <div className="mx-auto max-w-6xl space-y-4 px-4 py-6 sm:py-8">
        {failed && !data ? (
          <div role="alert" className="rounded-card bg-surface p-8 text-center shadow-card">
            <p className="font-semibold">Không tải được tổng quan. Vui lòng thử lại.</p>
            <Button className="mt-4" onClick={() => void load()}>
              Thử lại
            </Button>
          </div>
        ) : !data ? (
          <p className="py-10 text-center text-muted" aria-busy>
            Đang tải…
          </p>
        ) : (
          <>
            <div className="grid gap-4 lg:grid-cols-[1.45fr_1fr] lg:items-start">
              <div className="min-w-0 space-y-4">
                {/* Một khung: thẻ "Tiếp theo" (lịch chơi gần nhất) + danh sách Phòng đang trống (thiết kế prototype, người dùng 04/11) */}
                <section className={card} aria-labelledby="up-title">
                  <h2 id="up-title" className="sr-only">
                    Lịch chơi tiếp theo
                  </h2>
                  {next ? (
                    <NextCard item={next} today={data.today} nowMs={nowMs} />
                  ) : (
                    <div className="rounded-xl bg-primary-softer px-4 py-6 text-center ring-1 ring-primary/10">
                      <p className="text-muted">Bạn chưa có lịch chơi sắp tới</p>
                      <Link href="/hoi-vien/dat-san" className={cn(ctaCls, "mt-4")}>
                        Đặt sân
                      </Link>
                    </div>
                  )}
                  <OpenRooms rooms={data.open_rooms} busyId={busyId} onJoin={(r) => void requestJoin(r)} />
                </section>

                <UpcomingEvents events={data.upcoming_events} />
              </div>

              <RankCard ranking={data.ranking as Parameters<typeof RankCard>[0]["ranking"]} month={month} />
            </div>

            <RecordCards records={data.recent_records} />
          </>
        )}
      </div>
    </>
  );
}

// ------------------------------------------------------------------ 3 thẻ số trong banner

function StatCard({ href, label, month, value, unit, sub }: { href: string; label: string; month: number; value: string; unit: string; sub?: string }) {
  return (
    <Link
      href={href}
      aria-label={`${label} tháng ${month}: ${value} ${unit}. Xem chi tiết`}
      className="min-w-[72%] snap-start rounded-xl border border-surface/20 bg-surface/10 p-4 hover:bg-surface/15 focus-ring sm:min-w-0"
    >
      <span className="flex items-center justify-between gap-2 text-xs text-surface/85">
        <span>{label}</span>
        <span className="flex items-center gap-1.5">
          <span className="rounded-md bg-surface/15 px-2 py-0.5 font-semibold">Tháng {month}</span>
          <ArrowUpRight />
        </span>
      </span>
      <span className="mt-1.5 flex items-baseline gap-1.5 text-surface">
        <b className="text-3xl leading-none tabular-nums">{value}</b>
        {unit ? <span className="text-sm text-surface/80">{unit}</span> : null}
      </span>
      {sub ? <span className="mt-1 block text-xs text-surface/80">{sub}</span> : null}
    </Link>
  );
}

// ------------------------------------------------------------------ Tiếp theo

const dayLabel = (playDate: string, today: string) => (playDate === today ? "Hôm nay" : formatDayMonth(playDate));

/** Sân nhỏ vẽ bằng nét, avatar người trong phòng xếp trên mép sân (thẻ "Tiếp theo" theo prototype). */
function MiniCourt({ people }: { people: Upcoming["members_preview"] }) {
  return (
    <div className="relative hidden h-24 min-w-0 flex-1 sm:block" aria-hidden>
      <svg viewBox="0 0 160 70" preserveAspectRatio="none" className="absolute inset-x-0 bottom-0 h-16 w-full text-primary/40" fill="none" stroke="currentColor" strokeWidth="1.4">
        <rect x="1" y="1" width="158" height="68" />
        <path d="M80 1v68M1 35h158M30 1v68M130 1v68" />
      </svg>
      {people.length > 0 ? (
        <div className="absolute top-0 left-1/2 flex -translate-x-1/2 -space-x-2">
          {people.slice(0, 4).map((m, i) => (
            <Avatar key={`${m.display_name}-${i}`} url={m.avatar_url} name={m.display_name} size={34} className="ring-2 ring-surface" />
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** Thẻ "TIẾP THEO" theo prototype: nền xanh nhạt; trái = giờ, sân, Host, cụm avatar; phải = sân nhỏ + đếm ngược + Vào phòng. */
function NextCard({ item, today, nowMs }: { item: Upcoming; today: string; nowMs: number }) {
  const minutes = Math.ceil((Date.parse(item.start_at) - nowMs) / 60000);
  const ongoing = item.phase === "ongoing";
  const badge = ongoing ? "Đang diễn ra" : nowMs > 0 && minutes > 0 && minutes <= 60 ? `Còn ${minutes} phút` : null;
  return (
    <article className="flex flex-col gap-4 rounded-xl bg-primary-softer p-4 ring-1 ring-primary/10 sm:flex-row sm:p-5">
      <div className="min-w-0 flex-1">
        <p className="text-xs font-bold tracking-wider text-muted">TIẾP THEO</p>
        <p className="mt-1 text-2xl leading-tight font-bold">
          {dayLabel(item.play_date, today)} · <span className="tabular-nums">{hourRange(item.start_at, item.end_at)}</span>
        </p>
        <p className="mt-1 text-sm text-muted">
          {item.resource_name} · {item.resource_type_name} · Host: <b className="font-semibold text-foreground">{item.role === "host" ? "bạn" : item.host_name}</b>
        </p>
        {item.capacity !== null ? (
          <div className="mt-3 flex items-center gap-2">
            <div className="flex -space-x-1.5" aria-hidden>
              {item.members_preview.map((m, i) => (
                <Avatar key={`${m.display_name}-${i}`} url={m.avatar_url} name={m.display_name} size={26} className="ring-2 ring-surface" />
              ))}
            </div>
            <span className="text-sm font-semibold tabular-nums" aria-label={`${item.count} trên ${item.capacity} thành viên`}>
              {item.count}/{item.capacity}
            </span>
          </div>
        ) : (
          <p className="mt-3 text-sm text-muted">Phòng đang được tạo</p>
        )}
      </div>
      <div className="flex items-stretch gap-4 sm:w-[46%]">
        <MiniCourt people={item.members_preview} />
        <div className="flex flex-1 shrink-0 flex-col items-end justify-between gap-3 sm:flex-none">
          {badge ? (
            <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold", ongoing ? "bg-cta text-cta-fg" : "bg-appbar text-surface")}>
              <svg viewBox="0 0 20 20" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
                <circle cx="10" cy="11" r="6.5" />
                <path d="M10 8v3l2 1.5M8 2.5h4" />
              </svg>
              {badge}
            </span>
          ) : (
            <span aria-hidden />
          )}
          {item.room_id !== null ? (
            <Link href={`/hoi-vien/phong/${item.room_id}`} className="inline-flex h-11 items-center justify-center rounded-lg bg-primary px-5 text-sm font-semibold text-surface hover:bg-primary-hover focus-ring">
              Vào phòng
            </Link>
          ) : null}
        </div>
      </div>
    </article>
  );
}

// ------------------------------------------------------------------ Phòng đang trống

function OpenRooms({ rooms, busyId, onJoin }: { rooms: RoomCard[]; busyId: number | null; onJoin: (r: RoomCard) => void }) {
  return (
    <section className="mt-5" aria-labelledby="open-title">
      <div className="flex items-center justify-between gap-3">
        <h2 id="open-title" className="text-base font-bold">
          Phòng đang trống
        </h2>
        <Link href="/hoi-vien/danh-sach-san" className="rounded-sm text-sm font-semibold text-primary hover:underline focus-ring">
          Xem phòng chơi ›
        </Link>
      </div>
      {rooms.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted">Hôm nay chưa có phòng còn chỗ</p>
      ) : (
        <ul className="mt-2 divide-y divide-border">
          {rooms.map((r) => {
            const range = tierRangeText(r.tier_range);
            const reason = joinBlockText(r.my_join_block);
            return (
              <li key={r.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3">
                <span className="min-w-0 flex-1 basis-40">
                  <span className="block text-sm font-semibold">
                    {r.resource_name} · {hourRange(r.start_at, r.end_at)}
                  </span>
                  <span className="block truncate text-xs text-muted">Host: {r.host.display_name}</span>
                </span>
                {range ? <span className="rounded-full bg-primary-softer px-2.5 py-0.5 text-xs font-semibold text-primary ring-1 ring-primary/25">{range}</span> : null}
                <span className="text-sm font-semibold tabular-nums" aria-label={`${r.member_count} trên 8 thành viên`}>
                  {r.member_count}/8
                </span>
                {r.my_join_pending ? (
                  <Button variant="secondary" className="h-10 sm:h-10" disabled>
                    Đã xin vào
                  </Button>
                ) : (
                  <Button variant="secondary" className="h-10 sm:h-10" onClick={() => onJoin(r)} loading={busyId === r.id} disabled={Boolean(r.my_join_block)} title={reason ?? undefined}>
                    Xin vào
                  </Button>
                )}
                {reason && !r.my_join_pending ? (
                  <p role="note" className="basis-full text-xs text-muted">
                    {reason}
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ Hạng của tôi + Top 3

const MEDAL = ["bg-medal-gold", "bg-medal-silver", "bg-medal-bronze"];

// TẠM (T-053): `total_records` theo contract, bỏ phần giao này sau khi merge nhánh BE.
function RankCard({ ranking, month }: { ranking: Overview["ranking"] & { total_records: number }; month: number }) {
  const { me, top3, total_records } = ranking;
  const bar = me ? (me.gap_to_top10 === null || !me.top10_kmh ? 100 : Math.min(100, Math.round((me.speed_kmh / me.top10_kmh) * 100))) : 0;
  const inTop3 = top3.some((r) => r.is_me);
  return (
    <section className="rounded-xl border-2 border-accent bg-accent-soft/50 p-4 shadow-card sm:p-5" aria-labelledby="rank-title">
      <div className="flex items-center justify-between gap-3">
        <h2 id="rank-title" className="text-xs font-bold tracking-wide text-accent-fg">
          HẠNG CỦA TÔI · THÁNG {month}
        </h2>
        <Link href="/hoi-vien/bang-xep-hang" className="shrink-0 rounded-sm text-sm font-semibold text-primary hover:underline focus-ring">
          Bảng xếp hạng ›
        </Link>
      </div>

      {top3.length === 0 && !me ? (
        <p className="py-6 text-center text-sm text-muted">Chưa có số đo tốc độ trong tháng này</p>
      ) : (
        <>
          {me ? (
            <div className="mt-3">
              <div className="flex items-end justify-between gap-3">
                <p>
                  <b className="text-3xl tabular-nums">#{me.rank}</b> <span className="text-xs text-muted">/ {total_records} cú đập</span>
                </p>
                <p className="text-lg font-bold tabular-nums">{me.speed_kmh} km/h</p>
              </div>
              <div className="mt-2 h-2.5 overflow-hidden rounded-full bg-border" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={bar} aria-label="Tiến độ tới top 10">
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
              <h3 className="mt-5 text-xs font-bold tracking-wide text-accent-fg">TOP 3 THÁNG</h3>
              <ol className="mt-2 space-y-1">
                {top3.map((r, i) => (
                  <li key={r.rank} className={cn("flex items-center gap-2.5 rounded-lg px-2 py-1.5", r.is_me && "bg-surface/70")}>
                    <span aria-label={`Hạng ${r.rank}`} className={cn("grid size-6 shrink-0 place-items-center rounded-full text-xs font-bold text-medal-fg", MEDAL[i] ?? "bg-border")}>
                      {r.rank}
                    </span>
                    <Avatar url={r.avatar_url} name={r.display_name} size={28} />
                    <span className="min-w-0 flex-1 text-sm font-medium">
                      <span className="block truncate">
                        {r.display_name}
                        {r.is_me ? <span className="ml-1.5 rounded-full bg-surface px-2 py-0.5 text-xs font-semibold ring-1 ring-border">Bạn</span> : null}
                      </span>
                      <span className="block truncate text-xs font-normal text-muted tabular-nums">
                        {formatDayMonth(vnDate(r.measured_at))}
                        {(r as typeof r & { resource_name?: string | null }).resource_name ? ` · ${(r as typeof r & { resource_name?: string | null }).resource_name}` : ""}
                      </span>
                    </span>
                    <span className="text-sm font-bold tabular-nums">{r.speed_kmh} km/h</span>
                  </li>
                ))}
                {me && !inTop3 ? (
                  <li className="mt-1 flex items-center gap-2.5 rounded-lg bg-surface/70 px-2 py-1.5">
                    <span className="grid size-6 shrink-0 place-items-center text-xs font-semibold text-muted">{me.rank}</span>
                    <span className="min-w-0 flex-1 truncate text-sm font-medium">
                      <span className="rounded-full bg-surface px-2 py-0.5 text-xs font-semibold ring-1 ring-border">Bạn</span>
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

// ------------------------------------------------------------------ Kỷ lục mới

/** Vạch sân mờ làm nền ô video. */
function CourtLines() {
  return (
    <svg aria-hidden viewBox="0 0 320 180" preserveAspectRatio="xMidYMid slice" className="pointer-events-none absolute inset-0 size-full text-surface opacity-[0.12]" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="60" y="20" width="200" height="130" />
      <path d="M160 20v130M60 85h200M60 45h200M60 125h200M95 20v130M225 20v130" />
    </svg>
  );
}

// Khối chỉ để xem (người dùng 04/11): không có link sang màn khác, ô không bấm được; khi chưa có kỷ lục vẫn giữ khung chờ video
function RecordCards({ records }: { records: Overview["recent_records"] }) {
  // Thẻ đang phát video (T-046): chỉ một thẻ phát tại một thời điểm; iframe chỉ nạp sau khi bấm ▶
  const [playing, setPlaying] = useState<string | null>(null);
  return (
    <section className={card} aria-labelledby="rec-title">
      <h2 id="rec-title" className="text-base font-bold">
        Kỷ lục mới
      </h2>
      {/* Chưa có kỷ lục nào: vẫn giữ khung chờ video (người dùng 04/11) */}
      {records.length === 0 ? (
        <div className="relative mt-3 flex min-h-44 items-end overflow-hidden rounded-xl bg-appbar p-4 text-surface sm:max-w-sm">
          <CourtLines />
          <span aria-hidden className="absolute top-[38%] left-1/2 grid size-11 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-surface/20 ring-1 ring-surface/40">
            <svg viewBox="0 0 24 24" className="size-5 translate-x-px" fill="currentColor">
              <path d="M8 5.5v13l11-6.5z" />
            </svg>
          </span>
          <p className="relative text-sm text-surface/85">Chưa có kỷ lục mới trong tháng. Video cú đập kỷ lục sẽ hiện ở đây.</p>
        </div>
      ) : null}
      {records.length > 0 ? (
        <ul className="mt-3 grid gap-3 sm:grid-cols-3">
          {records.slice(0, 3).map((r) => {
            const k = `${r.measured_at}-${r.speed_kmh}`;
            const title = `${r.speed_kmh} km/h · ${r.display_name}`;
            return (
            <li key={k} className={cn("relative flex min-h-44 flex-col justify-end overflow-hidden rounded-xl bg-appbar p-4 text-surface", r.is_current && "ring-2 ring-accent")}>
              {r.video && playing === k ? (
                <VideoPlayer video={r.video} title={title} autoPlay className="relative mb-3" />
              ) : r.video ? (
                <button
                  type="button"
                  onClick={() => setPlaying(k)}
                  aria-label={`Phát video: ${title}`}
                  className="absolute top-3 right-3 z-10 grid size-11 place-items-center rounded-full bg-cta text-cta-fg shadow-card focus-ring"
                >
                  <svg viewBox="0 0 24 24" className="size-6 translate-x-px" fill="currentColor" aria-hidden>
                    <path d="M8 5.5v13l11-6.5z" />
                  </svg>
                </button>
              ) : (
                <span className="absolute top-3 right-3 rounded bg-black/45 px-1.5 py-0.5 text-[11px] font-medium text-surface/90">Chưa có video</span>
              )}
              <CourtLines />
              {r.is_current ? <span className="absolute top-3 left-3 rounded-full bg-accent px-2.5 py-1 text-xs font-bold text-cta-fg">Đang giữ kỷ lục</span> : null}
              <p className="relative flex flex-wrap items-baseline gap-2">
                <b className="text-3xl leading-none tabular-nums">{r.speed_kmh} km/h</b>
                {r.delta_kmh !== null ? <span className="rounded-md bg-surface/15 px-2 py-0.5 text-xs font-semibold text-accent-soft">+{r.delta_kmh} km/h</span> : null}
              </p>
              <p className="relative mt-1 flex items-center gap-2 text-sm font-semibold">
                <Avatar url={r.avatar_url} name={r.display_name} size={22} />
                <span className="truncate">{r.display_name}</span>
              </p>
              <p className="relative mt-0.5 truncate text-xs text-surface/80">{[r.racket, r.resource_name, shortDay(r.measured_at)].filter(Boolean).join(" · ")}</p>
            </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}

// ------------------------------------------------------------------ Sự kiện sắp tới (T-045)

/** Tối đa 3 sự kiện trong 14 ngày tới; không có thì ẩn cả khối. */
function UpcomingEvents({ events }: { events: Overview["upcoming_events"] }) {
  if (!events || events.length === 0) return null;
  return (
    <section className={card} aria-labelledby="ev-title">
      <div className="flex items-center justify-between gap-3">
        <h2 id="ev-title" className="text-base font-bold">
          Sự kiện sắp tới
        </h2>
        <Link href="/hoi-vien/danh-sach-san?loc=su-kien" className="rounded-sm text-sm font-semibold text-primary hover:underline focus-ring">
          Xem tất cả ›
        </Link>
      </div>
      <ul className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
        {events.map((e) => (
          <li key={e.code}>
            <EventCard e={e} />
          </li>
        ))}
      </ul>
    </section>
  );
}
