"use client";

import { type CSSProperties, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import type { LiveRecord } from "@/lib/live-records";
import { videoYoutubeId, youtubeEmbed } from "@/lib/video";

// Màn "Kỷ lục mới" toàn màn hình (người dùng 25/11), mở khi máy đo báo `record.new`:
// - chưa có video: ảnh đồ họa (sân + tia sáng + pháo giấy) với số km/h kỷ lục ở giữa;
// - `record.video` cùng record_id tới ⇒ nơi gọi truyền `record` mới có `video` ⇒ chuyển sang phát video toàn màn hình,
//   nhưng không sớm hơn HOLD_MS kể từ lúc mở (người dùng 26/11: video về rất nhanh, ảnh kỷ lục chưa kịp xem).
// Đóng bằng nút ✕ hoặc Esc. Giảm chuyển động ⇒ CSS tắt hiệu ứng (globals.css), số hiện ngay giá trị cuối.

const COUNT_MS = 1200;
const HOLD_MS = 10_000; // ảnh kỷ lục hiện ít nhất chừng này trước khi video thay thế, kể cả khi video đã về
// Pháo giấy: vị trí / độ trễ / màu cố định (không random lúc render ⇒ không lệch giữa các lần dựng)
const CONFETTI = Array.from({ length: 36 }, (_, i) => ({
  left: (i * 37) % 100,
  delay: ((i * 53) % 32) / 10,
  drift: `${((i * 29) % 21) - 10}vw`,
  size: 6 + ((i * 7) % 7),
  color: ["var(--cta)", "var(--surface)", "color-mix(in srgb, var(--cta) 60%, var(--surface))", "var(--primary-softer)"][i % 4],
  round: i % 3 === 0,
}));

/** true trong `ms` đầu tiên kể từ khi dựng (mỗi kỷ lục một lần: nơi gọi đặt `key` = record_id). */
function useHold(ms: number) {
  const [held, setHeld] = useState(true);
  useEffect(() => {
    const t = window.setTimeout(() => setHeld(false), ms);
    return () => window.clearTimeout(t);
  }, [ms]);
  return held;
}

/** Đếm từ 0 lên `to` trong COUNT_MS (giảm chuyển động ⇒ hiện ngay). */
function useCountUp(to: number) {
  // Chỉ dựng ở trình duyệt (sau tin websocket) nên đọc matchMedia ngay khi khởi tạo được
  const [calm] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const [value, setValue] = useState(calm ? to : 0);
  useEffect(() => {
    if (calm) return;
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / COUNT_MS);
      setValue(Math.round(to * (1 - (1 - t) ** 3)));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [to, calm]);
  return calm ? to : value;
}

export function LiveRecordTakeover({ record, onClose }: { record: LiveRecord; onClose: () => void }) {
  const closeBtn = useRef<HTMLButtonElement>(null);
  const speed = useCountUp(record.speed_kmh);
  const who = record.is_me ? "Bạn" : record.display_name;
  const held = useHold(HOLD_MS);
  const video = held ? null : record.video;
  const ytId = video?.kind === "youtube" ? videoYoutubeId(video) : null;

  useEffect(() => {
    closeBtn.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  return (
    <div role="dialog" aria-modal="true" aria-label={`Kỷ lục mới ${record.speed_kmh} km/h`} className="fixed inset-0 z-[100] overflow-hidden bg-[#06180f] text-surface animate-fade-in">
      {video ? (
        // Video cắt ghép đã có: phát toàn màn hình (tắt tiếng để trình duyệt cho tự phát), nhãn km/h ở góc
        <>
          {ytId ? (
            <iframe title={`${record.speed_kmh} km/h · ${who}`} src={`${youtubeEmbed(ytId)}&mute=1`} allow="autoplay; encrypted-media; fullscreen" allowFullScreen className="absolute inset-0 size-full" />
          ) : (
            <video src={video.url} autoPlay muted playsInline controls aria-label={`${record.speed_kmh} km/h · ${who}`} className="absolute inset-0 size-full bg-black object-contain" />
          )}
          <div className="pointer-events-none absolute top-4 left-4 rounded-2xl bg-black/55 px-4 py-2 backdrop-blur sm:top-6 sm:left-6">
            <p className="text-xs font-bold tracking-widest text-cta uppercase">Kỷ lục mới</p>
            <p className="text-2xl font-extrabold tabular-nums sm:text-3xl">
              {record.speed_kmh}
              <span className="ml-1 text-base font-bold">km/h</span>
            </p>
            <p className="text-sm text-surface/85">{who}</p>
          </div>
        </>
      ) : (
        // Chưa có video: ảnh đồ họa kỷ lục
        <>
          {/* Tia sáng xoay sau số */}
          <div aria-hidden className="absolute top-1/2 left-1/2 size-[160vmax] -translate-x-1/2 -translate-y-1/2 animate-rays-spin opacity-25" style={{ background: "repeating-conic-gradient(from 0deg, color-mix(in srgb, var(--cta) 55%, transparent) 0deg 6deg, transparent 6deg 20deg)", maskImage: "radial-gradient(circle, black 0%, transparent 60%)" }} />
          {/* Quầng sáng vàng */}
          <div aria-hidden className="absolute top-1/2 left-1/2 size-[70vmin] -translate-x-1/2 -translate-y-1/2 animate-glow-pulse rounded-full blur-3xl" style={{ background: "radial-gradient(circle, color-mix(in srgb, var(--cta) 45%, transparent), transparent 70%)" }} />
          {/* Sân cầu lông phối cảnh làm nền */}
          <svg aria-hidden viewBox="0 0 320 180" preserveAspectRatio="xMidYMax slice" className="absolute inset-0 size-full text-surface opacity-[0.12]" fill="none" stroke="currentColor" strokeWidth="1.2">
            <path d="M70 40h180l50 140H20zM100 80h120M45 125h230M160 40v140" />
          </svg>
          {/* Pháo giấy */}
          <div aria-hidden className="pointer-events-none absolute inset-0">
            {CONFETTI.map((c, i) => (
              <span
                key={i}
                className={cn("absolute top-0 block animate-confetti-fall", c.round ? "rounded-full" : "rounded-[2px]")}
                style={{ left: `${c.left}%`, width: c.size, height: c.round ? c.size : c.size * 1.6, background: c.color, animationDelay: `${c.delay}s`, "--drift": c.drift } as CSSProperties}
              />
            ))}
          </div>

          <div role="status" className="relative flex h-full flex-col items-center justify-center px-6 text-center">
            <p className="inline-flex animate-pop-in items-center gap-2 rounded-full bg-cta px-5 py-2 text-sm font-extrabold tracking-[0.2em] text-cta-fg uppercase shadow-lg sm:text-base">
              <svg viewBox="0 0 24 24" className="size-5" fill="currentColor" aria-hidden>
                <path d="M3 7l4.5 4L12 4l4.5 7L21 7l-2 12H5z" />
              </svg>
              Kỷ lục mới
            </p>
            <p className="mt-6 animate-speed-burst bg-gradient-to-b from-[#fff6d6] via-cta to-[#b8860b] bg-clip-text leading-none font-black tracking-tight text-transparent tabular-nums drop-shadow-[0_6px_30px_rgba(234,179,8,0.45)]" style={{ fontSize: "clamp(5rem, 22vmin, 15rem)" }}>
              {speed}
            </p>
            <p className="-mt-1 text-2xl font-extrabold tracking-wide text-cta sm:text-4xl">km/h</p>
            <p className="mt-6 animate-slide-up text-xl font-bold sm:text-3xl" style={{ animationDelay: "500ms" }}>
              {who}
            </p>
            {record.resource_name ? (
              <p className="mt-1 animate-slide-up text-sm text-surface/75 sm:text-base" style={{ animationDelay: "650ms" }}>
                {record.resource_name}
              </p>
            ) : null}
            <p className="absolute bottom-8 left-1/2 flex -translate-x-1/2 items-center gap-2 text-sm whitespace-nowrap text-surface/70">
              <span className="size-2 animate-pulse rounded-full bg-cta motion-reduce:animate-none" aria-hidden />
              {record.video ? "Video cú đập sắp phát…" : "Đang chờ video cú đập…"}
            </p>
          </div>
        </>
      )}

      <button ref={closeBtn} type="button" onClick={onClose} aria-label="Đóng" className="absolute top-4 right-4 grid size-12 place-items-center rounded-full bg-black/45 text-surface backdrop-blur hover:bg-black/65 focus-ring-inverse sm:top-6 sm:right-6">
        <svg viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden>
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    </div>
  );
}
