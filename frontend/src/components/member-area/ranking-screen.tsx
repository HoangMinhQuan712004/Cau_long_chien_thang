"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { PageBanner } from "@/components/member-area/page-banner";
import { type Clip, Podium } from "@/components/member-area/ranking-parts";
import { MyRank, RankRows } from "@/components/member-area/ranking-table";
import { RecordPlayer } from "@/components/records/record-player";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/cn";
import { addDaysIso, formatDayMonthYear, vnDate } from "@/lib/format";

// /hoi-vien/bang-xep-hang (T-030): top 10 cú đập nhanh nhất theo tuần / tháng / năm, bục top 3, hạng của tôi, hạng 4–10 có thanh tốc độ.
// T-049: dòng / bục / thẻ "Hạng của tôi" có video thì bấm được và mở popup với trình phát của T-048 (không tự phát); không có video thì giữ nguyên, không bấm được.

type Ranking = components["schemas"]["SpeedRanking"];
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

/** Popup xem video của một cú đập (T-049 AC2–AC4): dựng khi mở, gỡ khi đóng nên video dừng; <dialog> gốc trả focus về nút vừa bấm. */
function ClipDialog({ clip, onClose }: { clip: Clip; onClose: () => void }) {
  return (
    <Modal open onClose={onClose} size="wide" title={clip.name} subtitle={`${clip.speed} km/h${clip.measuredAt ? ` · đạt ${formatDayMonthYear(vnDate(clip.measuredAt))}` : ""}`}>
      <RecordPlayer video={clip.video} speed={clip.speed} name={clip.name} />
    </Modal>
  );
}

export function RankingScreen() {
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
  const top3 = (data?.top ?? []).slice(0, 3);
  const rest = (data?.top ?? []).slice(3, 10);
  // Đổi kỳ (Tuần / Tháng / Năm, kỳ trước / sau) ⇒ dựng lại các khối ⇒ chạy lại hiệu ứng "lên ngôi"
  const runKey = data ? `${data.period}-${data.start}` : "";
  const best = data?.top[0]?.speed_kmh ?? 0;
  const floor = data?.bar_floor_kmh ?? 200;

  return (
    <>
      <PageBanner
        title="Bảng xếp hạng"
        subtitle={data ? `Top 10 cú đập nhanh nhất · ${noun} ${periodTitle(data).replace(/^(Tháng|Năm) /, "")}` : "Top 10 cú đập nhanh nhất"}
        aside={
          // Điện thoại: tab kỳ + chọn kỳ chung một hàng (nút nhỏ lại); từ sm như cũ
          <div className="flex w-full items-center justify-between gap-2 sm:w-auto sm:flex-wrap sm:justify-start">
            <div role="tablist" aria-label="Kỳ xếp hạng" className="flex shrink-0 rounded-full bg-surface/15 p-1">
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
                  className={cn("h-8 rounded-full px-2.5 text-xs font-semibold focus-ring sm:h-9 sm:px-4 sm:text-sm", period === x.key ? "bg-surface text-primary-hover" : "text-surface/80 hover:text-surface")}
                >
                  {x.label}
                </button>
              ))}
            </div>
            {data ? (
              <div role="group" aria-label="Chọn kỳ" className="flex shrink-0 items-center gap-0.5 rounded-full bg-surface/15 p-1 sm:gap-1">
                <button type="button" aria-label="Kỳ trước" onClick={() => setAnchor(addDaysIso(data.start, -1))} className="grid size-7 place-items-center rounded-full hover:bg-surface/20 focus-ring sm:size-9">
                  <span aria-hidden>‹</span>
                </button>
                <span className="min-w-20 text-center text-xs font-semibold sm:min-w-28 sm:text-sm" aria-live="polite">
                  {periodTitle(data)}
                </span>
                <button
                  type="button"
                  aria-label="Kỳ sau"
                  disabled={!canNext}
                  onClick={() => setAnchor(addDaysIso(data.end, 1))}
                  className="grid size-7 place-items-center rounded-full hover:bg-surface/20 focus-ring disabled:opacity-40 disabled:hover:bg-transparent sm:size-9"
                >
                  <span aria-hidden>›</span>
                </button>
              </div>
            ) : null}
          </div>
        }
      >
        {/* key theo kỳ ⇒ đổi Tuần / Tháng / Năm hay kỳ trước / sau thì chạy lại hiệu ứng "lên ngôi" */}
        {top3.length > 0 && data ? <Podium key={runKey} top3={top3} onPlay={setClip} /> : null}
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
            <MyRank key={`me-${runKey}`} me={data.me ?? null} total={data.total_records} noun={noun} onPlay={setClip} />
            {rest.length > 0 ? <RankRows key={`rows-${runKey}`} rows={rest} best={best} floor={floor} onPlay={setClip} /> : null}
          </>
        )}
        <p className="flex items-start gap-2 px-1 text-xs text-muted">
          <svg viewBox="0 0 20 20" className="mt-px size-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
            <circle cx="10" cy="10" r="7.5" />
            <path d="M10 9v5M10 6.5v.01" strokeLinecap="round" />
          </svg>
          Chỉ hiện tên hội viên đã bật “Hiện trên Video &amp; kỷ lục” ở Hồ sơ của tôi; người khác hiện là Hội viên ẩn danh.
        </p>
      </div>
      {clip ? <ClipDialog clip={clip} onClose={() => setClip(null)} /> : null}
    </>
  );
}
