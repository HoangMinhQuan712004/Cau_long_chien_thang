"use client";

import { useEffect, useState } from "react";
import { Avatar } from "@/components/member-area/avatar";
import type { RecordBreakItem } from "@/components/records/requests";
import { RacketIcon } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import { formatDayMonth, formatTime, vnDate, weekdayIndex } from "@/lib/format";

// Thẻ kỷ lục bên cạnh trình phát (T-048 AC2, AC4): phần đầu vàng (số km/h có vệt sáng lướt + sao nháy), người phá kỷ lục
// + tổng thắng / thua trong Lịch sử chơi, Vợt / Sân / Thời điểm. Quyền riêng tư do server quyết định (T-030): trường null thì ẩn cả mục.

const WEEKDAY = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
const when = (iso: string) => `${WEEKDAY[weekdayIndex(vnDate(iso))]} ${formatDayMonth(vnDate(iso))} · ${formatTime(iso)}`;

const PinIcon = () => (
  <svg viewBox="0 0 24 24" className="size-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
    <path d="M12 21s7-6.2 7-11.5a7 7 0 0 0-14 0C5 14.8 12 21 12 21z" />
    <circle cx="12" cy="9.5" r="2.5" />
  </svg>
);
const CalendarIcon = () => (
  <svg viewBox="0 0 24 24" className="size-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
    <rect x="3.5" y="5" width="17" height="15" rx="2" />
    <path d="M3.5 10h17M8 3v4M16 3v4" />
  </svg>
);
const CrownIcon = ({ className }: { className?: string }) => (
  <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" aria-hidden>
    <path d="m3 8 4.5 4L12 5l4.5 7L21 8l-2 11H5z" />
  </svg>
);
const TrendIcon = () => (
  <svg viewBox="0 0 24 24" className="size-3.5 shrink-0" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="m3 17 6-6 4 4 8-8M15 7h6v6" />
  </svg>
);
const STAR_PATH = "M12 0C12.9 8.1 15.9 11.1 24 12C15.9 12.9 12.9 15.9 12 24C11.1 15.9 8.1 12.9 0 12C8.1 11.1 11.1 8.1 12 0Z";

/** Sao 4 cánh quanh số (như ảnh mẫu): `gold` = ruột vàng nhạt, viền vàng, quầng sáng; `dark` = nâu đậm nhỏ.
 * Luôn hiện, nháy sáng ↔ dịu; `delay` (s) cho các sao lệch nhịp. Giảm chuyển động ⇒ đứng yên. */
function GlintStar({ className, tone, delay }: { className: string; tone: "gold" | "dark"; delay: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden
      className={cn(
        "pointer-events-none absolute animate-star-glint",
        tone === "gold"
          ? "fill-[color-mix(in_srgb,var(--accent)_45%,white)] stroke-cta drop-shadow-[0_0_0.3rem_var(--cta)]"
          : "fill-[color-mix(in_srgb,var(--accent)_45%,black)]",
        className,
      )}
      strokeWidth={tone === "gold" ? 1.2 : 0}
      style={{ animationDelay: `${delay}s` }}
    >
      <path d={STAR_PATH} />
    </svg>
  );
}

/** Số chạy tăng dần tới `target` (~0,9 s, chậm dần) mỗi khi `target` đổi; giảm chuyển động ⇒ hiện ngay. */
function useCountUp(target: number, ms = 900): number {
  const [value, setValue] = useState(target);
  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const from = reduce ? target : Math.round(target * 0.6);
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const p = reduce ? 1 : Math.min(1, (now - start) / ms);
      setValue(Math.round(from + (target - from) * (1 - (1 - p) ** 3)));
      if (p < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, ms]);
  return value;
}

/** Vòng tỷ lệ thắng mọi thời gian trong Lịch sử chơi: cung xanh = phần thắng, % ở giữa. */
function WinRing({ rate }: { rate: number }) {
  const r = 22;
  const c = 2 * Math.PI * r;
  return (
    <div role="meter" aria-label="Tỷ lệ thắng trong Lịch sử chơi" aria-valuemin={0} aria-valuemax={100} aria-valuenow={rate} className="relative grid size-9 shrink-0 place-items-center">
      <svg viewBox="0 0 56 56" className="absolute inset-0 size-full -rotate-90" aria-hidden>
        <circle cx="28" cy="28" r={r} fill="none" strokeWidth="5" className="stroke-border" />
        <circle cx="28" cy="28" r={r} fill="none" strokeWidth="5" strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - rate / 100)} className="stroke-primary transition-[stroke-dashoffset] duration-500 motion-reduce:transition-none" />
      </svg>
      <b className="relative text-[0.625rem] tabular-nums">{rate}%</b>
    </div>
  );
}

/** Ô Vợt / Sân / Thời điểm (`gold`: nền vàng nhạt cho ô vợt). */
function InfoTile({ icon, label, gold = false, children }: { icon: React.ReactNode; label: string; gold?: boolean; children: React.ReactNode }) {
  return (
    <div className={cn("min-w-0 rounded-xl px-3 py-1", gold ? "bg-accent-soft" : "bg-primary-softer")}>
      <p className={cn("flex items-center gap-1.5 text-xs", gold ? "font-semibold text-accent-fg" : "text-muted")}>
        {icon}
        {label}
      </p>
      <p className="mt-0.5 font-semibold break-words">{children}</p>
    </div>
  );
}

/** Thẻ "Kỷ lục hiện tại" / "Kỷ lục ngày dd/mm" bên cạnh trình phát. Máy tính: phần thân gọn, phần đầu vàng giãn ra
 * cho thẻ cao bằng video 16:9 (không cắt video); thẻ nhiều chữ hơn thì cao hơn video một chút. */
export function RecordCard({ item }: { item: RecordBreakItem }) {
  const label = item.is_current ? "Kỷ lục hiện tại" : `Kỷ lục ngày ${formatDayMonth(item.label_date)}`;
  const stats = item.play_stats;
  const speed = useCountUp(item.speed_kmh);
  const delta = item.is_baseline || item.delta_kmh === null ? "Mốc đầu" : `+${item.delta_kmh} km/h${item.previous_kmh !== null ? ` · phá kỷ lục ${item.previous_kmh} km/h` : ""}`;
  return (
    <section aria-label={label} className="flex h-full flex-col overflow-hidden rounded-2xl bg-surface text-foreground shadow-card ring-2 ring-cta/80">
      {/* Phần đầu: nền vàng chuyển sắc + vệt sáng chéo + sao lấp lánh, căn giữa */}
      <div className="relative flex flex-1 flex-col items-center justify-center overflow-hidden text-center bg-linear-to-br from-accent-soft to-[color-mix(in_srgb,var(--accent)_38%,white)] px-5 py-2.5">
        {/* Một vạch sáng chéo hai mép song song bên phải (như ảnh mẫu); tràn qua mép trên / dưới để hai đầu không bị cắt lệch */}
        <span aria-hidden className="pointer-events-none absolute -inset-y-4 right-14 w-14 skew-x-[-20deg] bg-linear-to-b from-surface/60 via-surface/35 to-surface/15" />
        <p className="relative inline-flex items-center gap-1.5 rounded-full bg-cta px-4 py-0.5 text-sm font-bold tracking-wide text-cta-fg uppercase shadow-sm">
          <CrownIcon className="size-4.5" />
          {label}
        </p>
        <p className="relative mt-3 flex items-baseline justify-center gap-2.5">
          {/* Số chạy lên chỉ để nhìn; trình đọc màn hình đọc giá trị cuối */}
          <span className="relative">
            {/* 4 sao sát số (kiểu ảnh mẫu): vàng dưới chân số đầu · nâu nhỏ trên số · nâu nhỏ góc trên phải số · vàng lớn trên chữ km/h */}
            <GlintStar tone="gold" className="bottom-1 -left-4 size-4" delay={0} />
            <GlintStar tone="dark" className="-top-2 left-1/3 size-2" delay={0.6} />
            <GlintStar tone="gold" className="-top-1 -right-9 size-5" delay={0.9} />
            <GlintStar tone="dark" className="top-1 -right-2 size-2.5" delay={1.3} />
            <span aria-hidden className="bg-linear-to-b from-cta to-[color-mix(in_srgb,var(--accent)_55%,black)] bg-clip-text pb-1 font-serif text-[4.5rem] leading-none font-black text-transparent tabular-nums drop-shadow-sm">
              {speed}
            </span>
            {/* Vệt sáng chỉ lướt trong nét chữ số: lớp chữ trùng khít phía trên, nền là dải sáng chéo cắt theo chữ */}
            <span
              aria-hidden
              className="absolute inset-0 animate-shine-text bg-[linear-gradient(110deg,transparent_36%,var(--surface)_50%,transparent_64%)] bg-size-[250%_100%] bg-clip-text pb-1 font-serif text-[4.5rem] leading-none font-black text-transparent tabular-nums motion-reduce:hidden"
            >
              {speed}
            </span>
            <span className="sr-only">{item.speed_kmh}</span>
          </span>
          <span className="text-2xl font-semibold text-muted">km/h</span>
        </p>
        <p className="relative mt-2 inline-flex max-w-full items-center gap-1.5 rounded-full border border-cta bg-surface px-3 py-1 text-xs font-semibold text-accent-fg">
          <TrendIcon />
          <span className="truncate">{delta}</span>
        </p>
      </div>

      <div className="flex flex-col gap-2 px-4 pt-2.5 pb-4 sm:px-5">
        <div className="flex items-center gap-3">
          {/* Avatar viền vàng; vương miện khi đang giữ kỷ lục */}
          <div className="relative shrink-0 pt-2.5">
            {item.is_current ? <CrownIcon className="absolute top-0 left-4 z-10 size-7 -rotate-12 fill-cta text-cta-fg/60" /> : null}
            <div className="rounded-full bg-cta p-1 shadow-card">
              <Avatar url={item.avatar_url} name={item.display_name} size={52} />
            </div>
          </div>
          <div className="min-w-0 flex-1">
            {/* Tên không bao giờ bị cắt: đủ chỗ thì một hàng, màn hẹp tự xuống dòng; "Bạn" nằm cạnh biệt danh để tên đủ chỗ */}
            <p className="text-lg leading-tight font-bold break-words">
              {item.display_name}
            </p>
            {item.nickname || item.is_me ? (
              <p className="mt-0.5 flex items-center gap-2 text-sm">
                {item.nickname ? <span className="truncate font-semibold text-accent-fg">“{item.nickname}”</span> : null}
                {item.is_me ? <span className="shrink-0 rounded-full bg-primary-softer px-2 py-0.5 text-xs font-semibold text-primary">Bạn</span> : null}
              </p>
            ) : null}
            <p className="text-sm text-muted">{item.tier ? `Hội viên · Trình độ ${item.tier}` : "Hội viên"}</p>
          </div>
          {/* Tổng thắng / thua mọi thời gian của người chơi (đặt cạnh tên); chưa có trận / ẩn danh ⇒ ẩn */}
          {stats ? (
            <div className="flex shrink-0 flex-col items-center gap-0.5" title={`${stats.matches} trận trong Lịch sử chơi`}>
              <WinRing rate={Math.round((stats.wins / stats.matches) * 100)} />
              {/* 2 dòng ngắn ⇒ cột chỉ rộng bằng vòng, nhường chỗ cho tên */}
              <p className="text-center text-[0.6875rem] leading-tight whitespace-nowrap tabular-nums">
                <b className="block text-primary">{stats.wins} thắng</b>
                <span className="text-muted">{stats.losses} thua</span>
              </p>
            </div>
          ) : null}
        </div>

        {/* Vợt / Sân / Thời điểm: cùng một kiểu ô; vợt trọn hàng, nền vàng nhạt cho nổi, tên dài tối đa 2 dòng */}
        <div className="grid grid-cols-2 gap-2 text-sm">
          {item.racket ? (
            <div className="col-span-2">
              <InfoTile icon={<RacketIcon size={16} />} label="Vợt phá kỷ lục" gold>
                <span className="line-clamp-2" title={item.racket}>
                  {item.racket}
                </span>
              </InfoTile>
            </div>
          ) : null}
          {item.resource_name ? (
            <InfoTile icon={<PinIcon />} label="Sân">
              {item.resource_name}
            </InfoTile>
          ) : null}
          <div className={item.resource_name ? undefined : "col-span-2"}>
            <InfoTile icon={<CalendarIcon />} label="Thời điểm">
              <span className="tabular-nums">{when(item.measured_at)}</span>
            </InfoTile>
          </div>
        </div>
      </div>
    </section>
  );
}
