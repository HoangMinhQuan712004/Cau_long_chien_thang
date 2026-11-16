"use client";

import { useState } from "react";
import { Avatar } from "@/components/member-area/avatar";
import { VideoPlayer } from "@/components/records/video-player";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/cn";
import { vnDate } from "@/lib/format";
import { SectionHead } from "./overview-parts";

// "Kỷ lục mới" của Tổng quan: ô video tối (nội dung media) – bỏ khung trắng bao ngoài. Điện thoại / tablet vuốt ngang.
// Ô video chỉ để xem (không bấm sang màn khác); tiêu đề có "Xem tất cả" sang Video & kỷ lục (người dùng 12/11).
// Chưa có kỷ lục vẫn giữ khung chờ video.

type Records = components["schemas"]["Overview"]["recent_records"];

const WEEKDAY = ["CN", "T2", "T3", "T4", "T5", "T6", "T7"];
const shortDay = (iso: string) => {
  const d = vnDate(iso);
  return `${WEEKDAY[new Date(`${d}T00:00:00Z`).getUTCDay()]} ${d.slice(8, 10)}/${d.slice(5, 7)}`;
};

/** Vạch sân mờ làm nền ô video. */
function CourtLines() {
  return (
    <svg aria-hidden viewBox="0 0 320 180" preserveAspectRatio="xMidYMid slice" className="pointer-events-none absolute inset-0 size-full text-surface opacity-[0.12]" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="60" y="20" width="200" height="130" />
      <path d="M160 20v130M60 85h200M60 45h200M60 125h200M95 20v130M225 20v130" />
    </svg>
  );
}

const PlayIcon = ({ className }: { className: string }) => (
  <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden>
    <path d="M8 5.5v13l11-6.5z" />
  </svg>
);

export function RecordCards({ records }: { records: Records }) {
  // Chỉ một thẻ phát tại một thời điểm (T-046); iframe chỉ nạp sau khi bấm ▶
  const [playing, setPlaying] = useState<string | null>(null);
  return (
    <section aria-labelledby="rec-title">
      <SectionHead id="rec-title" title="Kỷ lục mới" href="/hoi-vien/video-ky-luc" link="Xem tất cả" />
      {records.length === 0 ? (
        <div className="relative mt-3 flex min-h-44 items-end overflow-hidden rounded-2xl bg-appbar p-4 text-surface sm:max-w-sm">
          <CourtLines />
          <span aria-hidden className="absolute top-[38%] left-1/2 grid size-11 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-surface/20 ring-1 ring-surface/40">
            <PlayIcon className="size-5 translate-x-px" />
          </span>
          <p className="relative text-sm text-surface/85">Chưa có kỷ lục mới trong tháng. Video cú đập kỷ lục sẽ hiện ở đây.</p>
        </div>
      ) : (
        <ul className="-mx-4 mt-3 flex snap-x snap-mandatory gap-3 overflow-x-auto scroll-px-4 px-4 pb-1 scrollbar-none lg:mx-0 lg:grid lg:grid-cols-3 lg:gap-4 lg:overflow-visible lg:px-0">
          {records.slice(0, 3).map((r) => {
            const k = `${r.measured_at}-${r.speed_kmh}`;
            const title = `${r.speed_kmh} km/h · ${r.display_name}`;
            return (
              <li key={k} className={cn("relative flex min-h-44 w-[82%] shrink-0 snap-start flex-col justify-end overflow-hidden rounded-2xl bg-appbar p-4 text-surface sm:w-[46%] lg:w-auto", r.is_current && "ring-2 ring-accent ring-inset")}>
                {r.video && playing === k ? (
                  <VideoPlayer video={r.video} title={title} autoPlay className="relative mb-3" />
                ) : r.video ? (
                  <button type="button" onClick={() => setPlaying(k)} aria-label={`Phát video: ${title}`} className="absolute top-3 right-3 z-10 grid size-11 place-items-center rounded-full bg-cta text-cta-fg shadow-card focus-ring">
                    <PlayIcon className="size-6 translate-x-px" />
                  </button>
                ) : (
                  <span className="absolute top-3 right-3 rounded bg-black/45 px-1.5 py-0.5 text-[0.6875rem] font-medium text-surface/90">Chưa có video</span>
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
      )}
    </section>
  );
}
