"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PageBanner } from "@/components/member-area/page-banner";
import { RoomHistory } from "@/components/play-rooms/room-history";
import { Button } from "@/components/ui/button";
import type { DateRangeValue } from "@/components/ui/date-range";
import { Modal } from "@/components/ui/modal";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/cn";
import { formatDayMonthYear, formatNumber, formatTime, todayVn } from "@/lib/format";
import { MAX_RANGE_DAYS, PlayHistoryFilters, daysBetween, thisMonth } from "./play-history-filters";

// /hoi-vien/lich-su-choi (T-029): các buổi đã chơi trong khoảng ngày (mặc định tháng này; phòng có ≥ 1 trận đã lưu), 3 thẻ số theo khoảng,
// bấm dòng mở popup các trận của buổi đó (ở lại màn này, không sang phòng).

type History = components["schemas"]["PlayHistory"];
type Item = components["schemas"]["PlayHistoryItem"];

const WEEKDAY = ["CN", "T2", "T3", "T4", "T5", "T6", "T7"];
const dayLabel = (d: string) => `${WEEKDAY[new Date(`${d}T00:00:00Z`).getUTCDay()]} ${d.slice(8, 10)}/${d.slice(5, 7)}/${d.slice(0, 4)}`;
const hours = (it: Item) => `${formatTime(it.start_at)}–${formatTime(it.end_at)}`;
/** So khớp không phân biệt hoa thường, dấu ("san 1" khớp "Sân 1"). */
const fold = (s: string) => s.normalize("NFD").replace(/\p{M}/gu, "").replace(/đ/gi, "d").toLowerCase();
const spanText = (r: DateRangeValue) => (r.from === r.to ? formatDayMonthYear(r.from) : `${formatDayMonthYear(r.from)} – ${formatDayMonthYear(r.to)}`);

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  return (
    <div className="min-w-0 rounded-xl border border-surface/20 bg-surface/10 p-3 sm:p-4">
      <p className="flex items-center gap-1 text-xs text-surface/80 sm:gap-1.5">
        {icon}
        <span className="truncate">{label}</span>
      </p>
      <p className="mt-1 text-2xl font-bold tabular-nums sm:text-3xl">{formatNumber(value)}</p>
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
  const [today] = useState(todayVn);
  const [range, setRange] = useState(() => thisMonth(today));
  const [data, setData] = useState<History | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [detail, setDetail] = useState<Item | null>(null);
  // Chữ tìm lọc tại máy trên các buổi của khoảng đã tải (không gọi lại API)
  const [q, setQ] = useState("");
  // Chỉ nhận kết quả của lần gọi mới nhất (đổi khoảng liên tiếp)
  const seq = useRef(0);
  const rangeError = daysBetween(range) >= MAX_RANGE_DAYS ? "Khoảng ngày tối đa 1 năm. Hãy chọn khoảng ngắn hơn." : "";

  const load = useCallback(async (r: DateRangeValue) => {
    const mine = ++seq.current;
    setFailed(false);
    setIsLoading(true);
    try {
      const { data: d, response } = await api.GET("/api/v1/member-area/play-history", { params: { query: { from: r.from, to: r.to } } });
      if (mine !== seq.current) return;
      if (response.status === 401) {
        window.location.replace(`/dang-nhap?next=${encodeURIComponent("/hoi-vien/lich-su-choi")}&ly-do=het-han`);
        return;
      }
      if (d) setData(d);
      else setFailed(true);
    } catch {
      if (mine === seq.current) setFailed(true);
    }
    if (mine === seq.current) setIsLoading(false);
  }, []);

  useEffect(() => {
    if (rangeError) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải khi đổi khoảng ngày
    void load(range);
  }, [load, range, rangeError]);

  const items = useMemo(() => data?.items ?? [], [data]);
  const shownItems = useMemo(() => {
    const needle = fold(q.trim());
    return needle ? items.filter((it) => fold(`${it.resource_name} ${it.resource_type_name} ${dayLabel(it.date)}`).includes(needle)) : items;
  }, [items, q]);
  const s = data?.summary;

  return (
    <>
      <PageBanner
        title="Lịch sử chơi"
        subtitle={`Các buổi bạn đã chơi tại cụm sân · ${spanText(range)}`}
      >
        {/* Điện thoại cũng 3 thẻ một hàng (thẻ gọn lại) ⇒ danh sách lên cao hơn */}
        <div className="relative mx-auto grid max-w-6xl grid-cols-3 gap-2 px-4 pb-14 sm:gap-3 sm:pb-16">
          <Stat icon={<IconCalendar />} label="Buổi chơi" value={s?.sessions ?? 0} />
          <Stat icon={<IconPulse />} label="Số trận" value={s?.matches ?? 0} />
          <Stat icon={<IconTrophy />} label="Trận thắng" value={s?.wins ?? 0} />
        </div>
      </PageBanner>

      <div className="relative mx-auto -mt-10 max-w-6xl px-4 pb-8 sm:-mt-12">
        {failed && !data ? (
          <div role="alert" className="rounded-card bg-surface p-8 text-center shadow-card">
            <p className="font-semibold">Không tải được lịch sử chơi. Vui lòng thử lại.</p>
            <Button className="mt-4" onClick={() => void load(range)}>
              Thử lại
            </Button>
          </div>
        ) : !data ? (
          <p className="rounded-card bg-surface p-10 text-center text-muted shadow-card" aria-busy>
            Đang tải…
          </p>
        ) : (
          <section className="rounded-card bg-surface p-4 shadow-card sm:p-5" aria-labelledby="ph-title" aria-busy={isLoading}>
            <div className="flex items-baseline justify-between gap-3">
              <h2 id="ph-title" className="text-base font-bold">
                Các buổi chơi
              </h2>
              {items.length > 0 ? (
                <span className="text-xs text-muted tabular-nums" aria-live="polite">
                  {q.trim() ? `${shownItems.length}/${items.length} buổi` : `${items.length} buổi · mới nhất ở trên`}
                </span>
              ) : null}
            </div>
            <div className="mt-3">
              <PlayHistoryFilters today={today} range={range} onRange={setRange} q={q} onSearch={setQ} error={rangeError} />
            </div>

            {items.length === 0 ? (
              <div className="py-10 text-center">
                <p className="font-semibold">Chưa có buổi chơi nào trong khoảng này</p>
                <p className="mt-1 text-sm text-muted">Chọn khoảng ngày khác ở trên, hoặc đặt sân để chơi. Các trận đã lưu kết quả trong Phòng chơi sẽ hiện ở đây.</p>
                <Link href="/hoi-vien/dat-san" className="mt-4 inline-flex h-11 items-center rounded-lg bg-cta px-6 text-sm font-bold tracking-wide text-cta-fg uppercase hover:bg-cta-hover focus-ring">
                  Đặt sân
                </Link>
              </div>
            ) : shownItems.length === 0 ? (
              <div className="py-10 text-center">
                <p className="font-semibold">Không có buổi nào khớp “{q.trim()}”</p>
                <p className="mt-1 text-sm text-muted">Thử tên sân khác, hoặc bỏ chữ tìm để xem mọi buổi trong khoảng.</p>
                <Button variant="secondary" className="mt-4" onClick={() => setQ("")}>
                  Bỏ chữ tìm
                </Button>
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
                {/* Đang tải khoảng mới: giữ danh sách cũ, làm mờ (không nhảy layout) */}
                <ul className={cn("mt-2 divide-y divide-border transition-opacity motion-reduce:transition-none", isLoading && "opacity-50")}>
                  {shownItems.map((it) => (
                    <li key={it.room_id}>
                      <button
                        type="button"
                        onClick={() => setDetail(it)}
                        aria-haspopup="dialog"
                        aria-label={`${dayLabel(it.date)}, ${it.resource_name}, ${hours(it)}: ${it.matches} trận, thắng ${it.wins}, thua ${it.losses}. Xem lịch sử trận`}
                        className="grid w-full items-center gap-x-3 gap-y-2 rounded-lg px-3 py-3 text-left hover:bg-primary-softer focus-ring sm:grid-cols-[1.3fr_1.5fr_1.2fr_0.7fr_0.7fr_0.7fr_1.5rem]"
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
                      </button>
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
      {detail ? (
        <Modal open onClose={() => setDetail(null)} size="large" sheet title={`${detail.resource_name} · ${hours(detail)}`} subtitle={dayLabel(detail.date)}>
          <RoomHistory roomId={detail.room_id} />
        </Modal>
      ) : null}
    </>
  );
}
