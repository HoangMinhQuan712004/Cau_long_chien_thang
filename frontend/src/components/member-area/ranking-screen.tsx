"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Avatar } from "@/components/member-area/avatar";
import { useMember } from "@/components/member-area/member-shell";
import { PageBanner } from "@/components/member-area/page-banner";
import { RecordPlayer } from "@/components/records/record-player";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/cn";
import { addDaysIso, formatDayMonthYear, vnDate } from "@/lib/format";
import type { RecordVideo } from "@/lib/video";

// /hoi-vien/bang-xep-hang (T-030): top 10 cú đập nhanh nhất theo tuần / tháng / năm, bục top 3, hạng của tôi, hạng 4–10 có thanh tốc độ.
// T-049: dòng / bục / thẻ "Hạng của tôi" có video thì bấm được và mở popup với trình phát của T-048 (không tự phát); không có video thì giữ nguyên, không bấm được.

type Ranking = components["schemas"]["SpeedRanking"];
// TẠM (T-049): `measured_at` / `video` do BE thêm; bỏ phần giao này sau khi merge nhánh BE và chạy gen:api.
type VideoFields = { video?: RecordVideo | null };
type Row = components["schemas"]["SpeedRankingRow"] & VideoFields & { measured_at?: string };
type Me = NonNullable<Ranking["me"]> & VideoFields;

/** Cú đập đang mở trong popup. */
type Clip = { name: string; speed: number; measuredAt?: string; video: RecordVideo };
type Period = Ranking["period"];

const PERIODS: { key: Period; label: string; noun: string }[] = [
  { key: "week", label: "Tuần", noun: "tuần" },
  { key: "month", label: "Tháng", noun: "tháng" },
  { key: "year", label: "Năm", noun: "năm" },
];
const dm = (d: string) => `${d.slice(8, 10)}/${d.slice(5, 7)}`;

/** Nhãn kỳ: "Tháng 10/2026" · "Năm 2026" · "01/10 – 07/10/2026". */
function periodTitle(r: Pick<Ranking, "period" | "start" | "end">) {
  if (r.period === "month") return `Tháng ${r.start.slice(5, 7)}/${r.start.slice(0, 4)}`;
  if (r.period === "year") return `Năm ${r.start.slice(0, 4)}`;
  return `${dm(r.start)} – ${dm(r.end)}/${r.end.slice(0, 4)}`;
}

const Bolt = ({ className }: { className?: string }) => (
  <svg viewBox="0 0 20 20" className={cn("size-4 shrink-0", className)} fill="currentColor" aria-hidden>
    <path d="M11 1.5 3.5 11H9l-1 7.5L16.5 8H11z" />
  </svg>
);
const Crown = () => (
  <svg viewBox="0 0 20 20" className="size-6 text-accent" fill="currentColor" aria-hidden>
    <path d="m3 6 3.5 3L10 4l3.5 5L17 6l-1.5 9h-11z" />
  </svg>
);

const PlayBadge = () => (
  <span aria-hidden className="grid size-6 shrink-0 place-items-center rounded-full bg-cta text-cta-fg shadow-card">
    <svg viewBox="0 0 24 24" className="size-3.5 translate-x-px" fill="currentColor">
      <path d="M8 5.5v13l11-6.5z" />
    </svg>
  </span>
);

/** Có video: nút bấm được (cả bàn phím, tối thiểu 44 px); không có: khối thường, hiển thị như trước. */
function Playable({ video, label, onPlay, className, children }: { video: RecordVideo | null | undefined; label: string; onPlay: () => void; className?: string; children: React.ReactNode }) {
  if (!video) return <div className={className}>{children}</div>;
  return (
    <button type="button" onClick={onPlay} aria-label={label} className={cn("min-h-11 cursor-pointer text-left focus-ring", className)}>
      {children}
    </button>
  );
}

const clipOf = (name: string, speed: number, measuredAt: string | undefined, video: RecordVideo | null | undefined): Clip | null => (video ? { name, speed, measuredAt, video } : null);

/** Popup xem video của một cú đập (T-049 AC2–AC4): dựng khi mở, gỡ khi đóng nên video dừng; <dialog> gốc trả focus về nút vừa bấm. */
function ClipDialog({ clip, onClose }: { clip: Clip; onClose: () => void }) {
  return (
    <Modal open onClose={onClose} size="wide" title={clip.name} subtitle={`${clip.speed} km/h${clip.measuredAt ? ` · đạt ${formatDayMonthYear(vnDate(clip.measuredAt))}` : ""}`}>
      <RecordPlayer video={clip.video} speed={clip.speed} name={clip.name} />
    </Modal>
  );
}

/** Người trong bảng: hiện tên + ảnh; ẩn danh thì chữ "?" trên nền xám. */
function Person({ row, size }: { row: Row; size: number }) {
  return <Avatar url={row.avatar_url} name={row.display_name} size={size} className={row.avatar_url ? "" : "bg-primary-hover"} />;
}

const PODIUM: Record<1 | 2 | 3, { block: string; ring: string; h: string; order: string }> = {
  1: { block: "bg-medal-gold", ring: "ring-medal-gold", h: "h-28 sm:h-36", order: "order-2" },
  2: { block: "bg-medal-silver", ring: "ring-medal-silver", h: "h-20 sm:h-24", order: "order-1" },
  3: { block: "bg-medal-bronze", ring: "ring-medal-bronze", h: "h-16 sm:h-20", order: "order-3" },
};

function PodiumPlace({ row, place, onPlay }: { row: Row; place: 1 | 2 | 3; onPlay: (c: Clip) => void }) {
  const p = PODIUM[place];
  const first = place === 1;
  return (
    <li className={cn("flex min-w-0 flex-1 flex-col items-center", p.order)} aria-label={`Hạng ${place}: ${row.display_name}, ${row.speed_kmh} ki-lô-mét một giờ${row.is_me ? ", là bạn" : ""}`}>
      <Playable
        video={row.video}
        label={`Hạng ${place}: ${row.display_name}, ${row.speed_kmh} ki-lô-mét một giờ. Xem video`}
        onPlay={() => {
          const c = clipOf(row.display_name, row.speed_kmh, row.measured_at, row.video);
          if (c) onPlay(c);
        }}
        className="flex w-full min-w-0 flex-col items-center rounded-lg"
      >
        {first ? <Crown /> : null}
        <span className={cn("rounded-full ring-4", p.ring)}>
          <Person row={row} size={first ? 72 : 56} />
        </span>
        <span className="mt-2 max-w-full truncate px-1 text-center text-sm font-semibold sm:text-base">
          {row.display_name}
          {row.is_me ? <span className="ml-1 text-xs font-normal text-surface/80">(Bạn)</span> : null}
        </span>
        <span className={cn("mt-1 inline-flex items-center gap-1 rounded-full px-3 py-1 font-bold tabular-nums", first ? "bg-accent text-medal-fg text-xl" : "bg-surface/15 text-lg")}>
          <Bolt />
          {row.speed_kmh}
          <span className="text-xs font-medium opacity-80">km/h</span>
          {row.video ? <PlayBadge /> : null}
        </span>
        <span aria-hidden className={cn("mt-3 grid w-full max-w-40 place-items-start justify-items-center rounded-t-lg pt-2 text-3xl font-bold text-medal-fg", p.block, p.h)}>
          {place}
        </span>
      </Playable>
    </li>
  );
}

export function RankingScreen() {
  const { me: profile } = useMember();
  const [period, setPeriod] = useState<Period>("month");
  const [anchor, setAnchor] = useState<string | undefined>(undefined);
  const [data, setData] = useState<Ranking | null>(null);
  const [failed, setFailed] = useState(false);
  const [nowMs, setNowMs] = useState(0);
  const [clip, setClip] = useState<Clip | null>(null);
  const seq = useRef(0);

  const load = useCallback(async (p: Period, date: string | undefined) => {
    const mine = ++seq.current;
    setFailed(false);
    try {
      const { data: d, response } = await api.GET("/api/v1/member-area/speed-ranking", { params: { query: { period: p, ...(date ? { date } : {}) } } });
      if (mine !== seq.current) return;
      if (response.status === 401) {
        window.location.replace(`/dang-nhap?next=${encodeURIComponent("/hoi-vien/bang-xep-hang")}&ly-do=het-han`);
        return;
      }
      if (d) {
        setData(d);
        setNowMs(Date.now());
      } else setFailed(true);
    } catch {
      if (mine === seq.current) setFailed(true);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải khi đổi kỳ
    void load(period, anchor);
  }, [load, period, anchor]);

  const today = nowMs ? vnDate(new Date(nowMs).toISOString()) : "";
  const canNext = Boolean(data && today && data.end < today);
  const noun = PERIODS.find((x) => x.key === period)?.noun ?? "";
  const rows: Row[] = data?.top ?? [];
  const top3 = rows.slice(0, 3);
  const rest = rows.slice(3, 10);
  const best = data?.top[0]?.speed_kmh ?? 0;
  const floor = data?.bar_floor_kmh ?? 200;
  const me: Me | null = data?.me ?? null;

  return (
    <>
      <PageBanner
        title="Bảng xếp hạng"
        subtitle={data ? `Top 10 cú đập nhanh nhất · ${noun} ${periodTitle(data).replace(/^(Tháng|Năm) /, "")}` : "Top 10 cú đập nhanh nhất"}
        aside={
          <div className="flex flex-wrap items-center gap-2">
            <div role="tablist" aria-label="Kỳ xếp hạng" className="flex rounded-full bg-surface/15 p-1">
              {PERIODS.map((x) => (
                <button
                  key={x.key}
                  type="button"
                  role="tab"
                  aria-selected={period === x.key}
                  onClick={() => {
                    setPeriod(x.key);
                    setAnchor(undefined);
                  }}
                  className={cn("h-9 rounded-full px-4 text-sm font-semibold focus-ring", period === x.key ? "bg-surface text-primary-hover" : "text-surface/80 hover:text-surface")}
                >
                  {x.label}
                </button>
              ))}
            </div>
            {data ? (
              <div role="group" aria-label="Chọn kỳ" className="flex items-center gap-1 rounded-full bg-surface/15 p-1">
                <button type="button" aria-label="Kỳ trước" onClick={() => setAnchor(addDaysIso(data.start, -1))} className="grid size-9 place-items-center rounded-full hover:bg-surface/20 focus-ring">
                  <span aria-hidden>‹</span>
                </button>
                <span className="min-w-28 text-center text-sm font-semibold" aria-live="polite">
                  {periodTitle(data)}
                </span>
                <button
                  type="button"
                  aria-label="Kỳ sau"
                  disabled={!canNext}
                  onClick={() => setAnchor(addDaysIso(data.end, 1))}
                  className="grid size-9 place-items-center rounded-full hover:bg-surface/20 focus-ring disabled:opacity-40 disabled:hover:bg-transparent"
                >
                  <span aria-hidden>›</span>
                </button>
              </div>
            ) : null}
          </div>
        }
      >
        {top3.length > 0 ? (
          <ol className="relative mx-auto flex max-w-2xl items-end gap-2 px-4 pt-6 sm:gap-6" aria-label="Top 3">
            {top3.map((r, i) => (
              <PodiumPlace key={r.rank} row={r} place={(i + 1) as 1 | 2 | 3} onPlay={setClip} />
            ))}
          </ol>
        ) : null}
      </PageBanner>

      <div className="relative mx-auto max-w-6xl space-y-4 px-4 py-6 sm:py-8">
        {failed && !data ? (
          <div role="alert" className="rounded-card bg-surface p-8 text-center shadow-card">
            <p className="font-semibold">Không tải được bảng xếp hạng. Vui lòng thử lại.</p>
            <Button className="mt-4" onClick={() => void load(period, anchor)}>
              Thử lại
            </Button>
          </div>
        ) : !data ? (
          <p className="py-10 text-center text-muted" aria-busy>
            Đang tải…
          </p>
        ) : data.top.length === 0 ? (
          <div className="rounded-card bg-surface p-10 text-center shadow-card">
            <p className="font-semibold">Chưa có số đo tốc độ trong kỳ này</p>
            <p className="mt-1 text-sm text-muted">Số đo được máy đo ghi nhận tự động; hãy thử kỳ khác.</p>
          </div>
        ) : (
          <>
            <section aria-label="Hạng của tôi" className="-mt-2 rounded-card border border-accent bg-accent-soft p-4 shadow-card sm:-mt-10 sm:p-5">
              {me ? (
                <div className="flex flex-col items-start gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-6">
                  <p>
                    <span className="block text-xs text-accent-fg">Hạng của tôi</span>
                    <b className="text-3xl tabular-nums">#{me.rank}</b>
                    <span className="ml-1 text-xs text-muted">/ {data.total_members} hội viên</span>
                  </p>
                  <span className="flex items-center gap-2">
                    <Avatar url={profile.avatar_url} name={profile.short_name} size={36} />
                    <b className="text-sm">{profile.short_name}</b>
                    <span className="rounded-full bg-surface px-2 py-0.5 text-xs font-semibold ring-1 ring-border">Bạn</span>
                  </span>
                  <p className="min-w-0 sm:flex-1">
                    <span className="block text-xs text-accent-fg">Kỷ lục trong {noun}</span>
                    <b className="tabular-nums">{me.speed_kmh} km/h</b>
                    <span className="ml-1 text-xs text-muted">đạt {formatDayMonthYear(vnDate(me.measured_at))}</span>
                  </p>
                  {me.video ? (
                    <Button
                      variant="secondary"
                      className="h-11 px-4 text-sm"
                      onClick={() => {
                        const c = clipOf(profile.short_name, me.speed_kmh, me.measured_at, me.video);
                        if (c) setClip(c);
                      }}
                    >
                      <span className="mr-2 inline-flex">
                        <PlayBadge />
                      </span>
                      Xem video
                    </Button>
                  ) : null}
                  {me.gap_to_top10 !== null ? (
                    <p className="rounded-xl border border-accent bg-surface px-4 py-2 text-center">
                      <span className="block text-xs text-accent-fg">Cách top 10</span>
                      <b className="text-lg text-accent-fg tabular-nums">+{me.gap_to_top10} km/h</b>
                    </p>
                  ) : null}
                </div>
              ) : (
                <p className="text-sm font-medium">Bạn chưa có số đo trong kỳ này</p>
              )}
            </section>

            {rest.length > 0 ? (
              <section className="rounded-card bg-surface p-4 shadow-card sm:p-5" aria-labelledby="rk-title">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h2 id="rk-title" className="text-base font-bold">
                    Hạng 4 – 10
                  </h2>
                  <span className="text-xs text-muted">Thanh tốc độ tính từ mốc {floor} km/h</span>
                </div>
                <ol className="mt-3 divide-y divide-border">
                  {rest.map((r) => {
                    const pct = best > floor ? Math.max(4, Math.min(100, Math.round(((r.speed_kmh - floor) / (best - floor)) * 100))) : 100;
                    return (
                      <li key={r.rank} className={cn(r.is_me && "rounded-lg bg-primary-softer px-2")}>
                        <Playable
                          video={r.video}
                          label={`Hạng ${r.rank}: ${r.display_name}, ${r.speed_kmh} ki-lô-mét một giờ. Xem video`}
                          onPlay={() => {
                            const c = clipOf(r.display_name, r.speed_kmh, r.measured_at, r.video);
                            if (c) setClip(c);
                          }}
                          className="grid w-full grid-cols-[2rem_1fr_auto] items-center gap-x-3 gap-y-1 py-2.5 sm:grid-cols-[2.5rem_12rem_1fr_4.5rem]"
                        >
                          <span className="grid size-7 place-items-center rounded-full bg-background text-xs font-bold tabular-nums ring-1 ring-border">{r.rank}</span>
                          <span className="flex min-w-0 items-center gap-2 text-sm font-medium">
                            <Person row={r} size={28} />
                            <span className="truncate">{r.display_name}</span>
                            {r.is_me ? <span className="rounded-full bg-surface px-2 py-0.5 text-xs font-semibold ring-1 ring-border">Bạn</span> : null}
                            {r.video ? <PlayBadge /> : null}
                          </span>
                          <span aria-hidden className="col-span-2 col-start-2 row-start-2 h-2.5 overflow-hidden rounded-full bg-border sm:col-span-1 sm:col-start-auto sm:row-start-auto">
                            <span className="block h-full rounded-full bg-linear-to-r from-primary-hover to-accent" style={{ width: `${pct}%` }} />
                          </span>
                          <span className="text-right text-sm font-bold tabular-nums">
                            {r.speed_kmh} <span className="text-xs font-normal text-muted">km/h</span>
                          </span>
                        </Playable>
                      </li>
                    );
                  })}
                </ol>
              </section>
            ) : null}
          </>
        )}
      </div>
      {clip ? <ClipDialog clip={clip} onClose={() => setClip(null)} /> : null}
    </>
  );
}
