"use client";

import { useState } from "react";
import { cn } from "@/lib/cn";
import { type RecordVideo, videoYoutubeId, youtubeEmbed, youtubeThumb } from "@/lib/video";

// Phát video kỷ lục tại chỗ (T-046 AC3–AC6). Khung 16:9 co theo chiều rộng.
// YouTube: chỉ hiện ảnh xem trước (i.ytimg.com), bấm ▶ mới nạp iframe youtube-nocookie (không tải script khi chưa bấm).
// File .mp4 / .webm: thẻ <video controls preload="metadata">.

const PlayIcon = () => (
  <svg viewBox="0 0 24 24" className="size-7 translate-x-px" fill="currentColor" aria-hidden>
    <path d="M8 5.5v13l11-6.5z" />
  </svg>
);

export function VideoPlayer({ video, title, className, autoPlay = false }: { video: RecordVideo; title: string; className?: string; autoPlay?: boolean }) {
  const [playing, setPlaying] = useState(autoPlay);
  const box = cn("relative aspect-video w-full overflow-hidden rounded-lg bg-black", className);

  if (video.kind === "file") {
    return (
      <div className={box}>
        <video controls preload="metadata" playsInline src={video.url} aria-label={title} className="size-full object-contain" autoPlay={autoPlay} />
      </div>
    );
  }
  const id = videoYoutubeId(video);
  if (!id) {
    return (
      <div className={cn(box, "grid place-items-center p-4 text-center text-sm text-white/80")}>
        <a href={video.url} target="_blank" rel="noopener noreferrer" className="underline focus-ring">
          Mở video
        </a>
      </div>
    );
  }
  return (
    <div className={box}>
      {playing ? (
        <iframe
          src={youtubeEmbed(id)}
          title={title}
          allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
          allowFullScreen
          referrerPolicy="strict-origin-when-cross-origin"
          className="absolute inset-0 size-full border-0"
        />
      ) : (
        <button type="button" onClick={() => setPlaying(true)} aria-label={`Phát video: ${title}`} className="group absolute inset-0 grid size-full place-items-center focus-ring">
          {/* eslint-disable-next-line @next/next/no-img-element -- ảnh xem trước của YouTube, không qua tối ưu ảnh của Next */}
          <img src={youtubeThumb(id)} alt="" loading="lazy" referrerPolicy="no-referrer" className="absolute inset-0 size-full object-cover" />
          <span className="absolute inset-0 bg-black/25 group-hover:bg-black/15" aria-hidden />
          <span className="relative grid size-14 place-items-center rounded-full bg-cta text-cta-fg shadow-card">
            <PlayIcon />
          </span>
        </button>
      )}
    </div>
  );
}
