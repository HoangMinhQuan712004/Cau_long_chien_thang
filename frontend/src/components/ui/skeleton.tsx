import { cn } from "@/lib/cn";

/** Khối giữ chỗ khi tải: nền viền, vệt sáng chạy ngang; kích thước do `className` quyết định. Là span nên đặt được trong h1/p. */
export function Skeleton({ className }: { className?: string }) {
  return <span aria-hidden className={cn("block animate-shimmer rounded-md bg-border", className)} />;
}

type SkeletonTableProps = {
  rows?: number;
  cols?: number;
  /** Câu "Đang tải…" cho trình đọc màn hình. */
  label?: string;
};

// Bề rộng các thanh lần lượt khác nhau cho tự nhiên
const WIDTHS = ["w-3/4", "w-1/2", "w-2/3", "w-2/5", "w-5/6"] as const;

/** Khung tải dạng bảng: máy tính là bảng có cột, điện thoại là thẻ xếp dọc (giống DataTable). */
export function SkeletonTable({ rows = 5, cols = 4, label }: SkeletonTableProps) {
  const rowKeys = Array.from({ length: rows }, (_, i) => i);
  const colKeys = Array.from({ length: cols }, (_, i) => i);
  const grid = { gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` };

  return (
    <div>
      {label ? (
        <p role="status" className="sr-only">
          {label}
        </p>
      ) : null}
      <div aria-hidden className="hidden overflow-hidden rounded-xl border md:block">
        <div style={grid} className="grid gap-4 bg-background px-4 py-3.5">
          {colKeys.map((c) => (
            <Skeleton key={c} className="h-3 w-1/2" />
          ))}
        </div>
        {rowKeys.map((r) => (
          <div key={r} style={grid} className="grid gap-4 border-t p-4">
            {colKeys.map((c) => (
              <Skeleton key={c} className={cn("h-4", WIDTHS[(r + c) % WIDTHS.length])} />
            ))}
          </div>
        ))}
      </div>
      <div aria-hidden className="divide-y rounded-xl border bg-surface md:hidden">
        {rowKeys.map((r) => (
          <div key={r} className="flex flex-col gap-2 px-3 py-2.5">
            {colKeys.map((c) => (
              <div key={c} className="flex justify-between gap-4">
                <Skeleton className="h-4 w-1/4" />
                <Skeleton className={cn("h-4", WIDTHS[(r + c) % WIDTHS.length], "max-w-1/2")} />
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
