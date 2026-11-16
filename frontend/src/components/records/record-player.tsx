"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { type RecordVideo, videoYoutubeId, youtubeEmbed, youtubeThumb } from "@/lib/video";

// Trình phát của màn Video & kỷ lục (T-048 AC3). Khung viền vàng, nhãn "Kỷ lục · n km/h", tên + km/h.
// - mp4 / webm: điều khiển riêng (phát/dừng, tua, thời gian, chậm 0.25x, toàn màn hình), preload="metadata", không tự phát.
// - YouTube: ảnh xem trước, bấm ▶ mới nạp iframe youtube-nocookie (dùng điều khiển của YouTube, không có nút 0.25x).
// - Không có video: khung "Chưa có video".
// Nơi gọi đặt `key` theo dòng đang chọn: đổi dòng thì trình phát cũ gỡ ra và dừng.

const Icon = ({ d, className = "size-5" }: { d: string; className?: string }) => (
  <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden>
    <path d={d} />
  </svg>
);
const PLAY = "M8 5.5v13l11-6.5z";
const PAUSE = "M7 5h4v14H7zM13 5h4v14h-4z";
const FULL = "M4 4h6v2H6v4H4zM14 4h6v6h-2V6h-4zM4 14h2v4h4v2H4zM18 14h2v6h-6v-2h4z";

const clock = (sec: number) => {
  const s = Number.isFinite(sec) && sec > 0 ? Math.floor(sec) : 0;
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

const ctrl = "grid size-11 shrink-0 place-items-center rounded-full text-surface hover:bg-surface/15 focus-ring-inverse sm:size-9";

export function RecordPlayer({ video, speed, name, className }: { video: RecordVideo | null; speed: number; name: string; className?: string }) {
  const title = `${speed} km/h · ${name}`;
  const ytId = video && video.kind === "youtube" ? videoYoutubeId(video) : null;
  const [ytPlaying, setYtPlaying] = useState(false);
  const hideOverlay = ytPlaying; // iframe đang chạy: nhường chỗ cho điều khiển của YouTube

  return (
    <div className={cn("relative aspect-video w-full overflow-hidden rounded-2xl bg-black shadow-card ring-2 ring-cta/80", className)}>
      {/* Hình sân mờ làm nền khi chưa có hình ảnh từ video */}
      <svg aria-hidden viewBox="0 0 320 180" preserveAspectRatio="none" className="absolute inset-0 size-full text-surface opacity-10" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M60 30h200l40 130H20zM90 70h140M50 110h220M160 30v130" />
      </svg>
      <span aria-hidden className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,color-mix(in_srgb,var(--primary)_30%,transparent),transparent_70%)]" />

      {!video ? (
        <div className="absolute inset-0 grid place-items-center text-center text-sm text-surface/80">
          <p>
            <svg viewBox="0 0 48 48" className="mx-auto mb-2 size-10 text-surface/60" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <rect x="5" y="12" width="28" height="24" rx="4" />
              <path d="m33 21 10-6v18l-10-6M6 6l36 36" />
            </svg>
            Chưa có video
          </p>
        </div>
      ) : video.kind === "file" ? (
        <FilePlayer url={video.url} title={title} />
      ) : ytId ? (
        ytPlaying ? (
          <iframe
            src={youtubeEmbed(ytId)}
            title={title}
            allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
            allowFullScreen
            referrerPolicy="strict-origin-when-cross-origin"
            className="absolute inset-0 size-full border-0"
          />
        ) : (
          <button type="button" onClick={() => setYtPlaying(true)} aria-label={`Phát video: ${title}`} className="group absolute inset-0 grid size-full place-items-center focus-ring-inverse">
            {/* eslint-disable-next-line @next/next/no-img-element -- ảnh xem trước của YouTube, không qua tối ưu ảnh của Next */}
            <img src={video.thumbnail_url?.startsWith("https://i.ytimg.com/") ? video.thumbnail_url : youtubeThumb(ytId)} alt="" referrerPolicy="no-referrer" className="absolute inset-0 size-full object-cover" />
            <span className="absolute inset-0 bg-black/35 group-hover:bg-black/20" aria-hidden />
            <span className="relative grid size-16 place-items-center rounded-full bg-cta text-cta-fg shadow-card">
              <Icon d={PLAY} className="size-8 translate-x-px" />
            </span>
          </button>
        )
      ) : (
        <div className="absolute inset-0 grid place-items-center p-4 text-center text-sm text-surface/80">
          <a href={video.url} target="_blank" rel="noopener noreferrer" className="underline focus-ring-inverse">
            Mở video
          </a>
        </div>
      )}

      {hideOverlay ? null : (
        <>
          <span className="pointer-events-none absolute top-3 left-3 inline-flex items-center gap-1.5 rounded-full border border-cta bg-black/55 px-3 py-1 text-xs font-bold tracking-wide text-cta uppercase">
            <svg viewBox="0 0 24 24" className="size-3.5" fill="currentColor" aria-hidden>
              <path d="M7 4h10v3a5 5 0 0 1-4 4.9V15h3v2H8v-2h3v-3.1A5 5 0 0 1 7 7zM4 5h2v3a3 3 0 0 1-2-2zm16 0v1a3 3 0 0 1-2 2V5zM8 19h8v2H8z" />
            </svg>
            Kỷ lục · {speed} km/h
          </span>
          <p className={cn("pointer-events-none absolute left-3 max-w-[calc(100%-1.5rem)] truncate text-sm font-semibold text-surface drop-shadow", video?.kind === "file" ? "bottom-14" : "bottom-3")}>
            {name} · <span className="text-cta tabular-nums">{speed} km/h</span>
          </p>
        </>
      )}
      {/* Bốn góc khung ngắm */}
      {(["top-2 left-2 border-t-2 border-l-2", "top-2 right-2 border-t-2 border-r-2", "bottom-2 left-2 border-b-2 border-l-2", "bottom-2 right-2 border-b-2 border-r-2"] as const).map((c) => (
        <span key={c} aria-hidden className={cn("pointer-events-none absolute size-5 rounded-sm border-cta", c)} />
      ))}
    </div>
  );
}

type WebkitVideo = HTMLVideoElement & { webkitEnterFullscreen?: () => void };

function FilePlayer({ url, title }: { url: string; title: string }) {
  const wrap = useRef<HTMLDivElement>(null);
  const vid = useRef<WebkitVideo>(null);
  const [playing, setPlaying] = useState(false);
  const [now, setNow] = useState(0);
  const [total, setTotal] = useState(0);
  const [slow, setSlow] = useState(false);
  const [failed, setFailed] = useState(false);

  // Một số trình duyệt đặt lại tốc độ khi nạp lại / kết thúc: áp lại mỗi lần đổi
  useEffect(() => {
    if (vid.current) vid.current.playbackRate = slow ? 0.25 : 1;
  }, [slow, playing]);

  const toggle = () => {
    const v = vid.current;
    if (!v) return;
    if (v.paused) void v.play().catch(() => setPlaying(false));
    else v.pause();
  };

  const fullscreen = () => {
    const el = wrap.current;
    const v = vid.current;
    if (document.fullscreenElement) void document.exitFullscreen();
    else if (el?.requestFullscreen) void el.requestFullscreen().catch(() => v?.webkitEnterFullscreen?.());
    else v?.webkitEnterFullscreen?.(); // iPhone chỉ cho phép toàn màn hình qua thẻ video
  };

  if (failed)
    return (
      <div className="absolute inset-0 grid place-items-center p-4 text-center text-sm text-surface/80">
        <a href={url} target="_blank" rel="noopener noreferrer" className="underline focus-ring-inverse">
          Không phát được, mở video
        </a>
      </div>
    );

  return (
    <div ref={wrap} className="absolute inset-0 bg-black">
      <video
        ref={vid}
        src={url}
        preload="metadata"
        playsInline
        aria-label={title}
        onClick={toggle}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={(e) => setNow(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => {
          setTotal(e.currentTarget.duration);
          e.currentTarget.playbackRate = slow ? 0.25 : 1;
        }}
        onError={() => setFailed(true)}
        className="size-full object-contain"
      />
      {playing ? null : (
        <button type="button" onClick={toggle} aria-label={`Phát video: ${title}`} className="absolute inset-0 m-auto grid size-16 place-items-center rounded-full bg-cta text-cta-fg shadow-card focus-ring-inverse">
          <Icon d={PLAY} className="size-8 translate-x-px" />
        </button>
      )}
      <div className="absolute inset-x-0 bottom-0 flex items-center gap-1 bg-gradient-to-t from-black/80 to-transparent px-2 pt-6 pb-1.5 sm:gap-2 sm:px-3">
        <button type="button" onClick={toggle} aria-label={playing ? "Dừng" : "Phát"} className={ctrl}>
          <Icon d={playing ? PAUSE : PLAY} />
        </button>
        <input
          type="range"
          aria-label="Tua video"
          min={0}
          max={total > 0 ? total : 0}
          step={0.1}
          value={Math.min(now, total || 0)}
          disabled={!(total > 0)}
          onChange={(e) => {
            const t = Number(e.target.value);
            if (vid.current) vid.current.currentTime = t;
            setNow(t);
          }}
          className="h-11 min-w-0 flex-1 accent-cta sm:h-9"
        />
        <span className="shrink-0 text-xs text-surface tabular-nums">
          {clock(now)} / {clock(total)}
        </span>
        <button
          type="button"
          aria-pressed={slow}
          onClick={() => setSlow((s) => !s)}
          className={cn("h-11 shrink-0 rounded-full border px-3 text-xs font-semibold focus-ring-inverse sm:h-8", slow ? "border-cta bg-cta text-cta-fg" : "border-surface/50 text-surface hover:bg-surface/15")}
        >
          Chậm 0.25x
        </button>
        <button type="button" onClick={fullscreen} aria-label="Toàn màn hình" className={ctrl}>
          <Icon d={FULL} />
        </button>
      </div>
    </div>
  );
}
