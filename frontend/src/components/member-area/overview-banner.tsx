import Link from "next/link";
import { cn } from "@/lib/cn";
import { ArrowUpRight, ctaCls } from "./overview-parts";
import { NetMesh } from "@/components/net-mesh";

// Banner đầu màn Tổng quan – kiểu "lưới" người dùng chọn 12/11: nền xanh đậm như header, mắt lưới cầu lông phủ cả banner
// và mờ dần ở mép trên/dưới (ombre 2 đầu – chuyển tiếp mềm sang header và phần thân); lời chào + Đặt sân; 3 ô số kính mờ.
// Điện thoại: lời chào ở app bar ⇒ sr-only, nút Đặt sân ở thanh dưới ⇒ ẩn; 3 số luôn hiện.

export type StatItem = { href: string; label: string; value: string; unit: string; sub?: string };
type Props = { title: React.ReactNode; subtitle: string; month: number; stats: StatItem[] };

const WRAP = "relative mx-auto max-w-6xl px-4";

function StatCell({ s, month }: { s: StatItem; month: number }) {
  return (
    <Link
      href={s.href}
      aria-label={`${s.label} tháng ${month}: ${s.value} ${s.unit}. Xem chi tiết`}
      className="group block min-w-0 rounded-xl bg-surface/10 p-3 ring-1 ring-surface/15 hover:bg-surface/15 focus-ring sm:p-5"
    >
      <span className="flex items-center justify-between gap-2 text-[0.6875rem] text-surface/75 sm:text-xs">
        <span className="truncate">{s.label}</span>
        <span className="hidden items-center gap-1 sm:flex">
          T{month} <ArrowUpRight className="opacity-60 group-hover:opacity-100" />
        </span>
      </span>
      <span className="mt-1 flex flex-col sm:mt-2 sm:flex-row sm:items-baseline sm:gap-1.5">
        <b className="text-2xl leading-none font-extrabold tabular-nums sm:text-4xl">{s.value}</b>
        {s.unit ? <span className="text-xs whitespace-nowrap text-surface/70 sm:text-sm">{s.unit}</span> : null}
      </span>
      {s.sub ? <span className="mt-1 line-clamp-2 block text-[0.6875rem] text-surface/65 sm:text-xs">{s.sub}</span> : null}
    </Link>
  );
}

export function OverviewBanner({ title, subtitle, month, stats }: Props) {
  return (
    <section className="relative isolate overflow-hidden bg-appbar text-surface">
      <NetMesh />
      <div className={cn(WRAP, "flex flex-wrap items-end justify-between gap-4 pt-3 lg:pt-10")}>
        <div className="min-w-0 max-lg:sr-only">
          <h1 className="text-3xl leading-tight font-extrabold tracking-tight xl:text-4xl">{title}</h1>
          <p className="mt-1.5 text-sm text-surface/75">{subtitle}</p>
        </div>
        <Link href="/hoi-vien/dat-san" className={cn(ctaCls, "shrink-0 max-lg:hidden")}>
          Đặt sân
        </Link>
      </div>
      <div className={cn(WRAP, "grid grid-cols-3 gap-2 pt-4 pb-5 sm:gap-4 lg:pt-8 lg:pb-8")}>
        {stats.map((s) => (
          <StatCell key={s.label} s={s} month={month} />
        ))}
      </div>
    </section>
  );
}
