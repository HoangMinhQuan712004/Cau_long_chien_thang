import Link from "next/link";
import { cn } from "@/lib/cn";

// Phần dùng chung của màn Tổng quan: tiêu đề khối (không khung – khối tách nhau bằng khoảng trắng), nút CTA, mũi tên.

export const ctaCls = cn(
  "inline-flex h-11 items-center justify-center rounded-lg bg-cta px-6 text-sm font-bold tracking-wide text-cta-fg",
  "uppercase hover:bg-cta-hover focus-ring",
);

export const ArrowUpRight = ({ className }: { className?: string }) => (
  <svg viewBox="0 0 20 20" className={cn("size-4 shrink-0", className)} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="M6 14 14 6M7 6h7v7" />
  </svg>
);

/** Tiêu đề khối + chữ phụ + link "Xem…" bên phải. */
export function SectionHead({ id, title, sub, href, link }: { id: string; title: string; sub?: string; href?: string; link?: string }) {
  return (
    <div className="flex items-end justify-between gap-3">
      <div className="min-w-0">
        <h2 id={id} className="text-lg font-bold tracking-tight sm:text-xl">
          {title}
        </h2>
        {sub ? <p className="mt-0.5 text-sm text-muted">{sub}</p> : null}
      </div>
      {href && link ? (
        <Link href={href} className="shrink-0 rounded-sm text-sm font-semibold text-primary hover:underline focus-ring">
          {link} ›
        </Link>
      ) : null}
    </div>
  );
}
