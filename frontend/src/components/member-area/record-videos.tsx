"use client";

import { useState } from "react";
import { RecordPlayer } from "@/components/records/record-player";
import type { MemberRecordVideo } from "@/components/records/requests";
import { Modal } from "@/components/ui/modal";
import { cn } from "@/lib/cn";
import { formatDayMonth, formatDayMonthYear, formatTime, vnDate } from "@/lib/format";
import { VideoThumb } from "./record-breaks";

// Tab "Tất cả video" của Video & kỷ lục (người dùng 27/11): mọi cú đập có video từ camera trong kỳ đang chọn, mới nhất trước
// (API record-videos, tối đa 60, đã ẩn danh như Bảng xếp hạng). Khác "Các lần phá kỷ lục": cả cú không phá kỷ lục chung
// (vd 248, 247 km/h sau kỷ lục 252). Bấm một dòng ⇒ popup phát video.

const who = (v: MemberRecordVideo) => (v.is_me ? "Bạn" : v.display_name);

export function AllVideos({ items, error, onRetry }: { items: MemberRecordVideo[] | null; error: string; onRetry: () => void }) {
  const [playing, setPlaying] = useState<MemberRecordVideo | null>(null);

  if (error)
    return (
      <div role="alert" className="mt-5 space-y-2 px-6 py-10 text-center text-sm">
        <p className="text-danger">{error}</p>
        <button type="button" onClick={onRetry} className="h-10 rounded-lg border border-border-strong px-4 font-semibold hover:bg-primary-softer focus-ring">
          Thử lại
        </button>
      </div>
    );
  if (items === null)
    return (
      <p className="mt-5 py-16 text-center text-muted" aria-busy>
        Đang tải…
      </p>
    );
  if (items.length === 0)
    return (
      <div className="mt-5 grid place-items-center px-6 py-16 text-center">
        <h3 className="text-lg font-bold">Chưa có video nào trong kỳ này</h3>
        <p className="mt-1 max-w-sm text-sm text-muted">Video do camera tự cắt sau mỗi cú đập được ghi nhận. Thử chọn kỳ dài hơn.</p>
      </div>
    );

  return (
    <>
      <ul className="mt-5 space-y-2">
        {items.map((v, i) => {
          const day = vnDate(v.measured_at);
          return (
            <li key={`${v.measured_at}-${i}`}>
              <button
                type="button"
                onClick={() => setPlaying(v)}
                aria-label={`Xem video ${v.speed_kmh} km/h của ${who(v)}, ${formatDayMonthYear(day)}`}
                className={cn("flex min-h-11 w-full items-center gap-3 rounded-xl border border-transparent px-2 py-2 text-left hover:bg-primary-softer focus-ring sm:gap-4 sm:px-3", v.is_me && "bg-accent-soft")}
              >
                <span className="w-12 shrink-0 text-center tabular-nums sm:w-14">
                  <b className="block text-base">{formatDayMonth(day)}</b>
                  <span className="text-xs text-muted">{day.slice(0, 4)}</span>
                </span>
                <VideoThumb video={v.video} />
                <span className="min-w-0 flex-1">
                  <b className="block text-lg tabular-nums">{v.speed_kmh} km/h</b>
                  <span className="block truncate text-sm font-semibold">{who(v)}</span>
                  <span className="block truncate text-xs text-muted tabular-nums">
                    {v.resource_name ? `${v.resource_name} · ` : ""}
                    {formatTime(v.measured_at)}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      {playing ? (
        <Modal open onClose={() => setPlaying(null)} size="wide" title={`${playing.speed_kmh} km/h · ${who(playing)}`} subtitle={`${formatDayMonthYear(vnDate(playing.measured_at))} · ${formatTime(playing.measured_at)}${playing.resource_name ? ` · ${playing.resource_name}` : ""}`}>
          <RecordPlayer video={playing.video} speed={playing.speed_kmh} name={who(playing)} />
        </Modal>
      ) : null}
    </>
  );
}
