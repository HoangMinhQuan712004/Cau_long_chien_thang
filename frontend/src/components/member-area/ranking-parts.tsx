"use client";

import { Avatar } from "@/components/member-area/avatar";
import { CrownIcon, GlintStar } from "@/components/member-area/record-card";
import { StageLights } from "@/components/member-area/stage-lights";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/cn";
import { vnDate } from "@/lib/format";
import type { RecordVideo } from "@/lib/video";

// Bục top 3 của Bảng xếp hạng (T-030, T-049, T-053) theo mẫu thiết kế: vương miện / huy chương, khối vàng – bạc – đồng số
// kiểu chữ có chân, hiệu ứng "lên ngôi". Thẻ "Hạng của tôi" + bảng 4–10 ở ranking-table.tsx. Có video thì bấm mở popup.

export type Row = components["schemas"]["SpeedRankingRow"];
export type Me = components["schemas"]["SpeedMe"];
/** Cú đập đang mở trong popup. */
export type Clip = { name: string; speed: number; measuredAt?: string; video: RecordVideo };

const dm = (d: string) => `${d.slice(8, 10)}/${d.slice(5, 7)}`;
/** "25/10 · Sân 5": ngày đạt (giờ VN) + sân – phân biệt các bậc của cùng một người (T-053 AC2). */
export const hitText = (r: Pick<Row, "measured_at" | "resource_name">) => `${dm(vnDate(r.measured_at))}${r.resource_name ? ` · ${r.resource_name}` : ""}`;

export const clipOf = (name: string, speed: number, measuredAt: string | undefined, video: RecordVideo | null | undefined): Clip | null =>
  video ? { name, speed, measuredAt, video } : null;

export const Bolt = ({ className }: { className?: string }) => (
  <svg viewBox="0 0 20 20" className={cn("size-4 shrink-0", className)} fill="currentColor" aria-hidden>
    <path d="M11 1.5 3.5 11H9l-1 7.5L16.5 8H11z" />
  </svg>
);

/** Huy chương có dây (hạng 2 bạc, hạng 3 đồng). */
const Medal = ({ className }: { className: string }) => (
  <svg viewBox="0 0 24 24" className={cn("size-6", className)} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" aria-hidden>
    <path d="M8 2h3l1 4M16 2h-3l-1 4" />
    <circle cx="12" cy="14.5" r="6" />
    <circle cx="12" cy="14.5" r="3" fill="currentColor" stroke="none" opacity="0.35" />
  </svg>
);

export const PlayBadge = () => (
  <span aria-hidden className="grid size-6 shrink-0 place-items-center rounded-full bg-cta text-cta-fg shadow-card">
    <svg viewBox="0 0 24 24" className="size-3.5 translate-x-px" fill="currentColor">
      <path d="M8 5.5v13l11-6.5z" />
    </svg>
  </span>
);

/** Có video: nút bấm được (cả bàn phím, tối thiểu 44 px); không có: khối thường. */
export function Playable({ video, label, onPlay, className, children }: { video: RecordVideo | null | undefined; label: string; onPlay: () => void; className?: string; children: React.ReactNode }) {
  if (!video) return <div className={className}>{children}</div>;
  return (
    <button type="button" onClick={onPlay} aria-label={label} className={cn("min-h-11 cursor-pointer text-left focus-ring", className)}>
      {children}
    </button>
  );
}

export const play = (r: Row, onPlay: (c: Clip) => void) => () => {
  const c = clipOf(r.display_name, r.speed_kmh, r.measured_at, r.video);
  if (c) onPlay(c);
};

// "Lên ngôi": khối mọc lên lần lượt hạng 3 → 2 → 1 rồi nội dung bật lên, hạng 1 cuối cùng + vương miện rơi xuống (ms)
const ENTER: Record<1 | 2 | 3, { block: number; content: number }> = { 3: { block: 0, content: 350 }, 2: { block: 150, content: 500 }, 1: { block: 300, content: 700 } };
const CROWN_DELAY = 1050;
const delay = (ms: number) => ({ animationDelay: `${ms}ms` });

// Bục: thứ tự hiển thị 2 – 1 – 3; khối chuyển sắc theo màu huy chương, số kiểu chữ có chân
// avatar: px máy tính · avatarSm: px điện thoại (< sm)
const PODIUM: Record<1 | 2 | 3, { order: string; ring: string; block: string; h: string; avatar: number; avatarSm: number }> = {
  1: {
    order: "order-2",
    ring: "ring-medal-gold shadow-[0_0_1.5rem_color-mix(in_srgb,var(--medal-gold)_55%,transparent)]",
    block: "from-[color-mix(in_srgb,var(--medal-gold)_70%,white)] to-medal-gold",
    h: "h-16 sm:h-28",
    avatar: 72,
    avatarSm: 52,
  },
  2: { order: "order-1", ring: "ring-medal-silver", block: "from-[color-mix(in_srgb,var(--medal-silver)_35%,white)] to-medal-silver", h: "h-12 sm:h-20", avatar: 56, avatarSm: 40 },
  3: { order: "order-3", ring: "ring-medal-bronze", block: "from-[color-mix(in_srgb,var(--medal-bronze)_60%,white)] to-medal-bronze", h: "h-9 sm:h-14", avatar: 56, avatarSm: 40 },
};

function PodiumPlace({ row, place, onPlay }: { row: Row; place: 1 | 2 | 3; onPlay: (c: Clip) => void }) {
  const p = PODIUM[place];
  const first = place === 1;
  const t = ENTER[place];
  return (
    <li className={cn("flex min-w-0 flex-1 flex-col items-center", p.order)} aria-label={`Hạng ${place}: ${row.display_name}, ${row.speed_kmh} ki-lô-mét một giờ${row.is_me ? ", là bạn" : ""}`}>
      <Playable
        video={row.video}
        label={`Hạng ${place}: ${row.display_name}, ${row.speed_kmh} ki-lô-mét một giờ. Xem video`}
        onPlay={play(row, onPlay)}
        className="flex w-full min-w-0 flex-col items-center rounded-lg"
      >
        {first ? (
          <span className="animate-crown-drop" style={delay(CROWN_DELAY)}>
            <CrownIcon className="size-6 text-cta sm:size-8" />
          </span>
        ) : (
          <span className="animate-pop-in" style={delay(t.content)}>
            <Medal className={cn("size-5 sm:size-6", place === 2 ? "text-medal-silver" : "text-medal-bronze")} />
          </span>
        )}
        {/* Avatar, tên, ngày · sân, viên tốc độ bật lên sau khi khối bục mọc xong */}
        <span className="flex w-full min-w-0 animate-pop-in flex-col items-center" style={delay(t.content)}>
        <span className="relative mt-1">
          {first ? (
            <>
              <GlintStar tone="gold" className="-top-9 -left-12 size-4" delay={0} />
              <GlintStar tone="gold" className="top-1 -right-14 size-3.5" delay={0.7} />
              <GlintStar tone="gold" className="bottom-0 -left-16 size-3" delay={1.3} />
              <GlintStar tone="gold" className="-top-4 -right-20 size-3" delay={1.8} />
            </>
          ) : null}
          <span className={cn("block rounded-full ring-3 sm:ring-4", p.ring)}>
            {/* Avatar nhận kích thước px ⇒ 2 bản: điện thoại nhỏ, từ sm như cũ */}
            <span className="sm:hidden">
              <Avatar url={row.avatar_url} name={row.display_name} size={p.avatarSm} className={row.avatar_url ? "" : "bg-surface! text-primary-hover!"} />
            </span>
            <span className="hidden sm:block">
              <Avatar url={row.avatar_url} name={row.display_name} size={p.avatar} className={row.avatar_url ? "" : "bg-surface! text-primary-hover!"} />
            </span>
          </span>
        </span>
        {/* Tên dài: xuống tối đa 2 dòng (căn giữa) thay vì cắt cụt; quá 2 dòng mới "…", rê / giữ để xem đủ */}
        <span title={row.display_name} className="mt-1.5 line-clamp-2 max-w-full px-0.5 text-center text-xs leading-tight font-bold break-words sm:mt-2 sm:px-1 sm:text-base">
          {row.display_name}
          {/* Điện thoại ẩn "(Bạn)" cho tên khỏi bị cắt */}
          {row.is_me ? <span className="ml-1 hidden text-xs font-normal text-surface/80 sm:inline">(Bạn)</span> : null}
        </span>
        {/* Ngày đạt · sân: phân biệt các bậc của cùng một người (T-053 AC2) */}
        <span className="max-w-full truncate px-0.5 text-center text-[0.625rem] text-surface/75 tabular-nums sm:px-1 sm:text-xs">{hitText(row)}</span>
        <span
          className={cn(
            // Điện thoại: viên nhỏ lại cho vừa cột (3 cột chia ~110 px)
            "mt-1 inline-flex max-w-full items-center gap-0.5 rounded-full px-2 py-0.5 font-bold tabular-nums sm:gap-1.5 sm:px-4 sm:py-1",
            first ? "bg-cta text-sm text-cta-fg shadow-card sm:text-2xl" : "bg-surface/15 text-xs ring-1 ring-surface/20 sm:text-xl",
          )}
        >
          <Bolt className={first ? "size-3.5 sm:size-5" : "size-3 text-cta sm:size-4"} />
          {row.speed_kmh}
          <span className="text-[0.5625rem] font-medium opacity-80 sm:text-xs">km/h</span>
          {/* Điện thoại ẩn nút ▶ trong viên (cả cột vẫn bấm được để xem video) */}
          {row.video ? (
            <span className="hidden sm:inline-flex">
              <PlayBadge />
            </span>
          ) : null}
        </span>
        </span>
        <span aria-hidden style={delay(t.block)} className={cn("mt-2 grid w-full max-w-20 origin-bottom animate-podium-rise place-items-center rounded-t-lg bg-linear-to-b font-serif text-2xl font-black text-medal-fg/85 sm:mt-3 sm:max-w-40 sm:text-4xl", p.block, p.h)}>
          {place}
        </span>
      </Playable>
    </li>
  );
}

/** Bục top 3 trong banner, có đèn rọi sân khấu. */
export function Podium({ top3, onPlay }: { top3: Row[]; onPlay: (c: Clip) => void }) {
  return (
    <div className="relative">
      <StageLights />
      {/* Khối bục sát đáy banner (chừa dải mỏng); thẻ "Hạng của tôi" kéo lên đè mép dưới banner (như mẫu) */}
      {/* Khung bục hẹp (điện thoại 20rem, máy tính 42rem) – đèn ở stage-lights.tsx dùng đúng bề rộng này; điện thoại:
          khối hẹp (5rem) + khe rộng cho 3 cột không dính nhau */}
      <ol className="relative mx-auto flex max-w-xs items-end gap-5 px-4 pt-2 pb-4 sm:max-w-2xl sm:gap-6 sm:px-4 sm:pt-4" aria-label="Top 3">
        {top3.map((r, i) => (
          <PodiumPlace key={r.rank} row={r} place={(i + 1) as 1 | 2 | 3} onPlay={onPlay} />
        ))}
      </ol>
    </div>
  );
}
