import Link from "next/link";
import { cn } from "@/lib/cn";
import { ChevronLeftIcon, ChevronRightIcon } from "./icons";

type PaginationProps = {
  page: number;
  pageCount: number;
  /** Đường dẫn của trang `n` (trạng thái nằm trên URL ⇒ F5 / gửi link không mất, nút Back dùng được). */
  hrefFor: (page: number) => string;
  t: { label: string; prev: string; next: string; page: string };
};

// Trang cần hiện: đầu, cuối, quanh trang hiện tại; khoảng trống ⇒ "…"
function pageItems(page: number, pageCount: number): (number | "gap")[] {
  const wanted = new Set([1, pageCount, page - 1, page, page + 1].filter((n) => n >= 1 && n <= pageCount));
  const sorted = [...wanted].sort((a, b) => a - b);
  return sorted.flatMap((n, i) => (i > 0 && n - sorted[i - 1] > 1 ? ["gap" as const, n] : [n]));
}

// Chữ / mũi tên trơn, không khung, không nền; vùng chạm mở rộng vô hình lên ≈44px
const ITEM = "relative grid size-8 place-items-center rounded-full before:absolute before:-inset-1.5";

/** Phân trang tối giản: ‹ 1 2 … 5 ›; rê chuột vòng tròn xanh nhạt, trang hiện tại chữ đậm màu chính. */
export function Pagination({ page, pageCount, hrefFor, t }: PaginationProps) {
  if (pageCount <= 1) return null;
  const pageLabel = (n: number) => t.page.replace("{n}", String(n));
  // Rê chuột: vòng tròn xanh nhạt + chữ màu chính
  const link = cn(ITEM, `
    text-muted focus-ring transition-colors
    hover:bg-primary-soft/60 hover:text-primary
  `);
  const step = (target: number, label: string, icon: React.ReactNode) =>
    target < 1 || target > pageCount ? (
      <span aria-hidden className={cn(ITEM, "text-muted opacity-30")}>
        {icon}
      </span>
    ) : (
      <Link href={hrefFor(target)} aria-label={label} className={link}>
        {icon}
      </Link>
    );

  return (
    <nav aria-label={t.label} className="flex flex-wrap items-center gap-1 text-ui tabular-nums">
      {step(page - 1, t.prev, <ChevronLeftIcon size={16} />)}
      {pageItems(page, pageCount).map((n, i) =>
        n === "gap" ? (
          <span key={`gap-${i}`} aria-hidden className="px-0.5 text-muted">
            …
          </span>
        ) : n === page ? (
          <span key={n} aria-current="page" aria-label={pageLabel(n)} className={cn(ITEM, `
            font-bold text-primary
          `)}>
            {n}
          </span>
        ) : (
          <Link key={n} href={hrefFor(n)} aria-label={pageLabel(n)} className={link}>
            {n}
          </Link>
        ),
      )}
      {step(page + 1, t.next, <ChevronRightIcon size={16} />)}
    </nav>
  );
}
