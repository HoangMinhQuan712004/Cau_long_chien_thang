"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { PageBanner } from "@/components/member-area/page-banner";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/cn";
import { formatNumber, formatTime, vnDate } from "@/lib/format";

// /hoi-vien/lich-su-choi (T-029): các buổi đã chơi trong tháng (phòng có ≥ 1 trận đã lưu), 3 thẻ số, bấm dòng mở Lịch sử trận của phòng.

type History = components["schemas"]["PlayHistory"];
type Item = components["schemas"]["PlayHistoryItem"];

const WEEKDAY = ["CN", "T2", "T3", "T4", "T5", "T6", "T7"];
const dayLabel = (d: string) => `${WEEKDAY[new Date(`${d}T00:00:00Z`).getUTCDay()]} ${d.slice(8, 10)}/${d.slice(5, 7)}/${d.slice(0, 4)}`;
const monthTitle = (m: string) => `Tháng ${m.slice(5, 7)}/${m.slice(0, 4)}`;
/** "2026-10" ± n tháng. */
const shiftMonth = (m: string, n: number) => {
  const d = new Date(Date.UTC(Number(m.slice(0, 4)), Number(m.slice(5, 7)) - 1 + n, 1));
  return d.toISOString().slice(0, 7);
};
const hours = (it: Item) => `${formatTime(it.start_at)}–${formatTime(it.end_at)}`;

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  return (
    <div className="rounded-xl border border-surface/20 bg-surface/10 p-4">
      <p className="flex items-center gap-1.5 text-xs text-surface/80">
        {icon}
        {label}
      </p>
      <p className="mt-1 text-3xl font-bold tabular-nums">{formatNumber(value)}</p>
    </div>
  );
}

const svg = "size-4 shrink-0";
const IconCalendar = () => (
  <svg viewBox="0 0 20 20" className={svg} fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
    <rect x="3" y="4.5" width="14" height="12" rx="2" />
    <path d="M3 8.5h14M7 3v3M13 3v3" />
  </svg>
);
const IconPulse = () => (
  <svg viewBox="0 0 20 20" className={svg} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="M2 10h3.5l2-5 4 10 2-5H18" />
  </svg>
);
const IconTrophy = () => (
  <svg viewBox="0 0 20 20" className={cn(svg, "text-accent")} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="M6 3h8v5a4 4 0 0 1-8 0zM6 5H3.5a2 2 0 0 0 2 3M14 5h2.5a2 2 0 0 1-2 3M10 12v3M7 17h6" />
  </svg>
);

export function PlayHistoryScreen() {
  const [month, setMonth] = useState<string | undefined>(undefined);
  const [data, setData] = useState<History | null>(null);
  const [failed, setFailed] = useState(false);
  const [nowMs, setNowMs] = useState(0);
  // Chỉ nhận kết quả của lần gọi mới nhất (đổi tháng liên tiếp)
  const seq = useRef(0);

  const load = useCallback(async (m: string | undefined) => {
    const mine = ++seq.current;
    setFailed(false);
    try {
      const { data: d, response } = await api.GET("/api/v1/member-area/play-history", { params: { query: m ? { month: m } : {} } });
      if (mine !== seq.current) return;
      if (response.status === 401) {
        window.location.replace(`/dang-nhap?next=${encodeURIComponent("/hoi-vien/lich-su-choi")}&ly-do=het-han`);
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
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải khi đổi tháng
    void load(month);
  }, [load, month]);

  const current = nowMs ? vnDate(new Date(nowMs).toISOString()).slice(0, 7) : "";
  const shown = data?.month ?? month ?? "";
  const canNext = Boolean(shown && current && shown < current);
  const s = data?.summary;

  return (
    <>
      <PageBanner
        title="Lịch sử chơi"
        subtitle={shown ? `Các buổi bạn đã chơi tại cụm sân · tháng ${shown.slice(5, 7)}/${shown.slice(0, 4)}` : "Các buổi bạn đã chơi tại cụm sân"}
        aside={
          shown ? (
            <div className="flex items-center gap-1 rounded-full bg-surface/15 p-1" role="group" aria-label="Chọn tháng">
              <button
                type="button"
                aria-label="Tháng trước"
                onClick={() => setMonth(shiftMonth(shown, -1))}
                className="grid size-9 place-items-center rounded-full hover:bg-surface/20 focus-ring"
              >
                <span aria-hidden>‹</span>
              </button>
              <span className="min-w-28 text-center text-sm font-semibold" aria-live="polite">
                {monthTitle(shown)}
              </span>
              <button
                type="button"
                aria-label="Tháng sau"
                disabled={!canNext}
                onClick={() => setMonth(shiftMonth(shown, 1))}
                className="grid size-9 place-items-center rounded-full hover:bg-surface/20 focus-ring disabled:opacity-40 disabled:hover:bg-transparent"
              >
                <span aria-hidden>›</span>
              </button>
            </div>
          ) : null
        }
      >
        <div className="relative mx-auto grid max-w-6xl gap-3 px-4 pb-14 sm:grid-cols-3 sm:pb-16">
          <Stat icon={<IconCalendar />} label="Buổi chơi" value={s?.sessions ?? 0} />
          <Stat icon={<IconPulse />} label="Số trận" value={s?.matches ?? 0} />
          <Stat icon={<IconTrophy />} label="Trận thắng" value={s?.wins ?? 0} />
        </div>
      </PageBanner>

      <div className="mx-auto -mt-10 max-w-6xl px-4 pb-8 sm:-mt-12">
        {failed && !data ? (
          <div role="alert" className="rounded-card bg-surface p-8 text-center shadow-card">
            <p className="font-semibold">Không tải được lịch sử chơi. Vui lòng thử lại.</p>
            <Button className="mt-4" onClick={() => void load(month)}>
              Thử lại
            </Button>
          </div>
        ) : !data ? (
          <p className="rounded-card bg-surface p-10 text-center text-muted shadow-card" aria-busy>
            Đang tải…
          </p>
        ) : (
          <section className="rounded-card bg-surface p-4 shadow-card sm:p-5" aria-labelledby="ph-title">
            <div className="flex items-baseline justify-between gap-3">
              <h2 id="ph-title" className="text-base font-bold">
                Các buổi chơi
              </h2>
              {data.items.length > 0 ? <span className="text-xs text-muted">Mới nhất ở trên</span> : null}
            </div>

            {data.items.length === 0 ? (
              <div className="py-10 text-center">
                <p className="font-semibold">Tháng này bạn chưa có trận nào</p>
                <p className="mt-1 text-sm text-muted">Các trận đã lưu kết quả trong Phòng chơi sẽ hiện ở đây.</p>
                <Link href="/hoi-vien/dat-san" className="mt-4 inline-flex h-11 items-center rounded-lg bg-primary px-5 text-sm font-semibold text-surface focus-ring sm:h-9.5">
                  Đặt sân
                </Link>
              </div>
            ) : (
              <>
                {/* Từ sm: bảng; điện thoại: mỗi buổi là một thẻ */}
                <div aria-hidden className="mt-3 hidden grid-cols-[1.3fr_1.5fr_1.2fr_0.7fr_0.7fr_0.7fr_1.5rem] gap-3 rounded-lg bg-primary-softer px-3 py-2 text-xs font-semibold tracking-wide text-muted uppercase sm:grid">
                  <span>Ngày</span>
                  <span>Sân</span>
                  <span>Khung giờ</span>
                  <span className="text-center">Số trận</span>
                  <span className="text-center">Thắng</span>
                  <span className="text-center">Thua</span>
                  <span />
                </div>
                <ul className="mt-2 divide-y divide-border">
                  {data.items.map((it) => (
                    <li key={it.room_id}>
                      <Link
                        href={`/hoi-vien/phong/${it.room_id}?tab=history`}
                        aria-label={`${dayLabel(it.date)}, ${it.resource_name}, ${hours(it)}: ${it.matches} trận, thắng ${it.wins}, thua ${it.losses}. Xem lịch sử trận`}
                        className="grid items-center gap-x-3 gap-y-2 rounded-lg px-3 py-3 hover:bg-primary-softer focus-ring sm:grid-cols-[1.3fr_1.5fr_1.2fr_0.7fr_0.7fr_0.7fr_1.5rem]"
                      >
                        <span className="font-semibold tabular-nums">{dayLabel(it.date)}</span>
                        <span className="text-sm">
                          <b>{it.resource_name}</b> <span className="text-xs text-muted">· {it.resource_type_name}</span>
                        </span>
                        <span className="text-sm tabular-nums">{hours(it)}</span>
                        <span className="flex items-center justify-between text-sm sm:contents">
                          <span className="text-muted sm:hidden">Số trận</span>
                          <span className="text-center tabular-nums sm:block">{it.matches}</span>
                        </span>
                        <span className="flex items-center justify-between text-sm sm:contents">
                          <span className="text-muted sm:hidden">Thắng</span>
                          <b className="text-center tabular-nums sm:block">{it.wins}</b>
                        </span>
                        <span className="flex items-center justify-between text-sm sm:contents">
                          <span className="text-muted sm:hidden">Thua</span>
                          <span className="text-center text-muted tabular-nums sm:block">{it.losses}</span>
                        </span>
                        <span aria-hidden className="hidden text-muted sm:block">
                          ›
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
        )}
        <p className="mt-4 flex items-start gap-2 px-1 text-xs text-muted">
          <svg viewBox="0 0 20 20" className="mt-px size-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
            <circle cx="10" cy="10" r="7.5" />
            <path d="M10 9v5M10 6.5v.01" strokeLinecap="round" />
          </svg>
          Chỉ tính các trận đã lưu kết quả trong Phòng chơi. Ở 2 vs 2, cả 2 người đội thắng đều được tính 1 trận thắng.
        </p>
      </div>
    </>
  );
}
