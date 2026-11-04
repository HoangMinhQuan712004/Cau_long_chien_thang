"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Avatar } from "@/components/member-area/avatar";
import { type MemberRecordVideo, getMemberVideos, type VideoPeriod } from "@/components/records/requests";
import { VideoPlayer } from "@/components/records/video-player";
import { errorText } from "@/lib/api/write";
import { cn } from "@/lib/cn";
import { formatDate } from "@/lib/format";
import { PageBanner } from "./page-banner";

// /hoi-vien/video-ky-luc (T-046): video kỷ lục do Admin gắn, lọc theo kỳ. Tên theo quy tắc ẩn danh T-030 (server quyết định).

const PERIODS: { key: VideoPeriod; label: string }[] = [
  { key: "week", label: "Tuần" },
  { key: "month", label: "Tháng" },
  { key: "year", label: "Năm" },
  { key: "all", label: "Mọi thời gian" },
];

export function VideoScreen() {
  const [period, setPeriod] = useState<VideoPeriod>("all");
  const [items, setItems] = useState<MemberRecordVideo[] | null>(null);
  const [error, setError] = useState("");
  const seq = useRef(0);

  const load = useCallback(async (p: VideoPeriod) => {
    const n = ++seq.current;
    setItems(null);
    setError("");
    const res = await getMemberVideos(p);
    if (n !== seq.current) return; // chỉ nhận kết quả của lần gọi mới nhất
    if (res.ok) setItems(res.data.items);
    else setError(errorText(res.error));
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải lại khi đổi kỳ
    void load(period);
  }, [load, period]);

  return (
    <>
      <PageBanner title="Video & kỷ lục" subtitle="Cú cầu nhanh nhất cụm sân · video chỉ đăng khi có kỷ lục mới" />
      <div className="mx-auto max-w-6xl px-4 py-6 sm:py-8">
        <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0" role="group" aria-label="Kỳ kỷ lục">
          {PERIODS.map((p) => (
            <button
              key={p.key}
              type="button"
              aria-pressed={period === p.key}
              onClick={() => setPeriod(p.key)}
              className={cn("h-11 shrink-0 rounded-full border px-5 text-sm font-semibold whitespace-nowrap focus-ring sm:h-10", period === p.key ? "border-primary-hover bg-primary-hover text-surface" : "border-border-strong bg-surface hover:bg-primary-softer")}
            >
              {p.label}
            </button>
          ))}
        </div>

        {error ? (
          <div role="alert" className="mt-5 space-y-2 rounded-xl bg-surface px-6 py-10 text-center text-sm shadow-card">
            <p className="text-danger">{error}</p>
            <button type="button" onClick={() => void load(period)} className="h-10 rounded-lg border border-border-strong px-4 font-semibold hover:bg-primary-softer focus-ring">
              Thử lại
            </button>
          </div>
        ) : items === null ? (
          <p className="mt-5 py-16 text-center text-muted" aria-busy>
            Đang tải…
          </p>
        ) : items.length === 0 ? (
          <div className="mt-5 grid place-items-center rounded-xl bg-surface px-6 py-16 text-center shadow-card">
            <svg viewBox="0 0 48 48" className="size-12 text-subtle" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <rect x="5" y="12" width="28" height="24" rx="4" />
              <path d="m33 21 10-6v18l-10-6M6 6l36 36" />
            </svg>
            <h2 className="mt-4 text-lg font-bold">Chưa có video</h2>
            <p className="mt-1 max-w-sm text-sm text-muted">{period === "all" ? "Video sẽ hiện ở đây khi cụm sân gắn video cho kỷ lục." : "Chưa có video nào trong kỳ này. Thử chọn kỳ dài hơn."}</p>
          </div>
        ) : (
          <ul className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((r) => {
              const title = `${r.speed_kmh} km/h · ${r.display_name}`;
              return (
                <li key={`${r.measured_at}-${r.speed_kmh}-${r.display_name}`} className="space-y-3 rounded-xl bg-surface p-3 shadow-card">
                  <VideoPlayer video={r.video} title={title} />
                  <div className="space-y-1 px-1 pb-1">
                    <p className="flex items-baseline justify-between gap-2">
                      <b className="text-xl tabular-nums">{r.speed_kmh} km/h</b>
                      <span className="text-xs text-muted tabular-nums">{formatDate(r.measured_at)}</span>
                    </p>
                    <p className="flex items-center gap-2 text-sm font-semibold">
                      <Avatar url={r.avatar_url} name={r.display_name} size={22} />
                      <span className="truncate">{r.display_name}</span>
                      {r.is_me ? <span className="rounded-full bg-primary-softer px-2 py-0.5 text-xs font-semibold text-primary">Bạn</span> : null}
                    </p>
                    {r.resource_name ? <p className="truncate text-xs text-muted">{r.resource_name}</p> : null}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </>
  );
}
