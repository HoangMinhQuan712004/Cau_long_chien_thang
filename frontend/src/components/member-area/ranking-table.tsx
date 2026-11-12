"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Avatar } from "@/components/member-area/avatar";
import { Bolt, type Clip, type Me, PlayBadge, Playable, type Row, clipOf, hitText, play } from "@/components/member-area/ranking-parts";
import { CrownIcon } from "@/components/member-area/record-card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { formatDayMonthYear, vnDate } from "@/lib/format";

// Thẻ "Hạng của tôi" (số hạng leo dần) + bảng hạng 4–10 (dòng trượt vào, thanh tốc độ chạy dài; thứ hạng đổi thì dòng
// trượt nhẹ tới chỗ mới) của Bảng xếp hạng. Chỉ animate transform / opacity; giảm chuyển động ⇒ hiện ngay.

const REDUCED = "(prefers-reduced-motion: reduce)";
const reduced = () => window.matchMedia(REDUCED).matches;
const rowKey = (r: Row) => `${r.display_name}|${r.measured_at}`;

/** Số hạng leo dần từ hạng thấp hơn (tối đa +10, không quá `total`) lên `target` trong ~1 s, chậm dần cuối. */
function useClimb(target: number, total: number): number {
  const [value, setValue] = useState(target);
  useEffect(() => {
    const from = Math.min(Math.max(total, target), target + 10);
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const p = reduced() ? 1 : Math.min(1, (now - start) / 1000);
      setValue(Math.round(from + (target - from) * (1 - (1 - p) ** 3)));
      if (p < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, total]);
  return value;
}

/** Đổi hạng (FLIP, nhẹ nhất): đo hết chỗ cũ / chỗ mới rồi mỗi dòng chỉ trượt `transform` tới chỗ mới – không đổ bóng,
 *  không đổi màu nền (đỡ vẽ lại), trình duyệt xử lý bằng card đồ hoạ. */
function useFlip<T extends HTMLElement>(order: string) {
  const ref = useRef<T>(null);
  const tops = useRef(new Map<string, number>());
  useLayoutEffect(() => {
    const items = Array.from(ref.current?.querySelectorAll<HTMLElement>("[data-flip]") ?? []);
    const moves = items.map((el) => {
      const key = el.dataset.flip ?? "";
      const top = el.getBoundingClientRect().top;
      const before = tops.current.get(key);
      return { el, key, top, dy: before === undefined ? 0 : before - top };
    });
    tops.current = new Map(moves.map((m) => [m.key, m.top]));
    if (reduced()) return;
    for (const m of moves) {
      if (m.dy) m.el.animate([{ transform: `translateY(${m.dy}px)` }, { transform: "none" }], { duration: 500, easing: "cubic-bezier(0.2, 0.8, 0.2, 1)" });
    }
  }, [order]);
  return ref;
}

/** Thẻ "Hạng của tôi": viền vàng nhấn bên trái, các mục ngăn bằng vạch dọc, "Cách top 10" ô vàng bên phải. */
export function MyRank({ me, total, noun, onPlay }: { me: Me | null; total: number; noun: string; onPlay: (c: Clip) => void }) {
  const rank = useClimb(me?.rank ?? 0, total);
  return (
    <section aria-label="Hạng của tôi" className="relative z-10 -mt-7 overflow-hidden rounded-card border border-accent/60 bg-surface shadow-[0_0.75rem_2rem_-0.5rem_color-mix(in_srgb,var(--foreground)_28%,transparent)] sm:-mt-10">
      <span aria-hidden className="absolute inset-y-0 left-0 w-1.5 bg-cta" />
      {me ? (
        // Điện thoại: lưới 2 cột – Hạng | Kỷ lục ở trên, tên + "Bạn" (và nút video / cách top 10) ở dưới; từ sm một hàng
        <div className="grid grid-cols-2 gap-x-3 gap-y-2.5 p-3 pl-5 sm:flex sm:flex-row sm:items-center sm:gap-0 sm:p-5 sm:pl-7">
          <p className="order-1 sm:order-none sm:pr-6">
            <span className="flex items-center gap-1 text-xs text-muted">
              <CrownIcon className="size-3.5 text-cta" />
              Hạng của tôi
            </span>
            {/* Số hạng leo dần lên hạng thật ("lên ngôi"); trình đọc màn hình đọc hạng thật */}
            <b className="text-xl tabular-nums sm:text-2xl" aria-hidden>
              #{rank}
            </b>
            <span className="sr-only">Hạng {me.rank}</span>
            <span className="ml-1 text-xs text-muted sm:ml-1.5">/ {total} cú đập</span>
          </p>
          <span className="order-3 col-span-2 flex items-center gap-2 border-t pt-2.5 sm:order-none sm:border-t-0 sm:border-l sm:px-6 sm:pt-0">
            <span className="rounded-full p-0.5 ring-2 ring-cta">
              <Avatar url={me.avatar_url} name={me.display_name} size={28} className={me.avatar_url ? "" : "bg-surface! text-primary-hover!"} />
            </span>
            <b className="text-sm">{me.display_name}</b>
            <span className="rounded-full bg-primary-softer px-2 py-0.5 text-xs font-semibold text-primary">Bạn</span>
          </span>
          <p className="order-2 min-w-0 sm:order-none sm:flex-1 sm:border-l sm:px-6">
            <span className="flex items-center gap-1 text-xs text-muted">
              <Bolt className="size-3.5 text-cta" />
              Kỷ lục trong {noun}
            </span>
            <b className="text-base tabular-nums sm:text-xl">{me.speed_kmh} km/h</b>
            <span className="block text-xs text-muted sm:ml-1.5 sm:inline">đạt {formatDayMonthYear(vnDate(me.measured_at))}</span>
          </p>
          {me.video ? (
            <Button variant="secondary" className="order-4 h-10 px-3 text-sm sm:order-none sm:mr-4 sm:h-11 sm:px-4" onClick={() => {
              const c = clipOf(me.display_name, me.speed_kmh, me.measured_at, me.video);
              if (c) onPlay(c);
            }}>
              <span className="mr-2 inline-flex">
                <PlayBadge />
              </span>
              Xem video
            </Button>
          ) : null}
          {me.gap_to_top10 !== null ? (
            <p className="order-4 rounded-xl border border-accent bg-accent-soft px-3 py-1.5 text-center sm:order-none sm:px-5 sm:py-2">
              <span className="block text-xs text-accent-fg">Cách top 10</span>
              <b className="text-base text-accent-fg tabular-nums sm:text-xl">+{me.gap_to_top10} km/h</b>
            </p>
          ) : null}
        </div>
      ) : (
        <p className="p-3 pl-5 text-sm font-medium sm:p-5 sm:pl-7">Bạn chưa có số đo trong kỳ này</p>
      )}
    </section>
  );
}

// Nền chữ cái avatar hạng 4–10 xoay vòng màu nhạt (như mẫu), lấy từ token
// (`!`: thắng màu mặc định bg-primary / text-surface của Avatar)
const TINTS = [
  "bg-[color-mix(in_srgb,var(--info)_14%,white)]! text-info!",
  "bg-[color-mix(in_srgb,var(--danger)_12%,white)]! text-danger!",
  "bg-[color-mix(in_srgb,var(--info)_10%,var(--accent-soft))]! text-primary-hover!",
  "bg-accent-soft! text-accent-fg!",
  "bg-primary-softer! text-primary!",
];

/** Màu nền chữ cái theo tên (không theo vị trí) ⇒ đổi hạng thì màu vẫn đi theo người. */
const tintOf = (name: string) => TINTS[[...name].reduce((h, ch) => (h * 31 + ch.charCodeAt(0)) >>> 0, 7) % TINTS.length];

/** Bảng hạng 4–10 (không hàng tiêu đề): hạng · hội viên · thanh tốc độ (xanh → vàng, tính từ mốc `floor`) · km/h. */
export function RankRows({ rows, best, floor, onPlay }: { rows: Row[]; best: number; floor: number; onPlay: (c: Clip) => void }) {
  const list = useFlip<HTMLOListElement>(rows.map(rowKey).join());
  // Hiệu ứng vào (trượt vào, thanh chạy dài) chỉ cho lần hiện đầu: di chuyển dòng trong DOM làm trình duyệt chạy lại
  // animation CSS ⇒ gỡ class sau khi vào xong để lúc đổi hạng không bị mờ / chạy lại
  const [entered, setEntered] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setEntered(true), 1600);
    return () => clearTimeout(t);
  }, []);
  const grid = "grid grid-cols-[2rem_1fr_auto] items-center gap-x-3 gap-y-1 sm:grid-cols-[3rem_14rem_1fr_5rem]";
  return (
    <section className="rounded-card bg-surface p-4 shadow-card sm:p-5" aria-labelledby="rk-title">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="rk-title" className="text-base font-bold">
          Hạng 4 – 10
        </h2>
        <span className="text-xs text-muted">Thanh tốc độ tính từ mốc {floor} km/h</span>
      </div>
      <ol ref={list} className="mt-2 divide-y">
        {rows.map((r, i) => {
          const pct = best > floor ? Math.max(4, Math.min(100, Math.round(((r.speed_kmh - floor) / (best - floor)) * 100))) : 100;
          return (
            // Khoá theo cú đập (không theo hạng) ⇒ thứ hạng đổi thì dòng trượt tới chỗ mới; vào lần đầu: trượt vào lần lượt
            <li key={rowKey(r)} data-flip={rowKey(r)} className={cn(!entered && "animate-row-in", r.is_me && "rounded-lg bg-primary-softer")} style={{ animationDelay: `${300 + i * 70}ms` }}>
              <Playable video={r.video} label={`Hạng ${r.rank}: ${r.display_name}, ${r.speed_kmh} ki-lô-mét một giờ. Xem video`} onPlay={play(r, onPlay)} className={cn(grid, "w-full px-1 py-2.5")}>
                <span className="grid size-7 place-items-center rounded-full text-xs font-bold tabular-nums ring-1 ring-border">{r.rank}</span>
                <span className="flex min-w-0 items-center gap-2.5 text-sm font-medium">
                  <Avatar url={r.avatar_url} name={r.display_name} size={30} className={r.avatar_url ? "" : tintOf(r.display_name)} />
                  <span className="min-w-0">
                    {/* Tên dài xuống tối đa 2 dòng thay vì cắt cụt */}
                    <span title={r.display_name} className="line-clamp-2 leading-tight break-words">
                      {r.display_name}
                    </span>
                    <span className="block truncate text-xs font-normal text-muted tabular-nums">{hitText(r)}</span>
                  </span>
                  {r.is_me ? <span className="shrink-0 rounded-full bg-surface px-2 py-0.5 text-xs font-semibold ring-1 ring-border">Bạn</span> : null}
                  {r.video ? <PlayBadge /> : null}
                </span>
                <span aria-hidden className="col-span-2 col-start-2 row-start-2 h-2 overflow-hidden rounded-full bg-border sm:col-span-1 sm:col-start-auto sm:row-start-auto">
                  <span className={cn("block h-full origin-left rounded-full bg-linear-to-r from-primary-hover via-primary to-cta", !entered && "animate-grow-x")} style={{ width: `${pct}%`, animationDelay: `${400 + i * 70}ms` }} />
                </span>
                <span className="text-right text-sm font-bold tabular-nums">
                  {r.speed_kmh} <span className="text-xs font-normal text-muted">km/h</span>
                </span>
              </Playable>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
