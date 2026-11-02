import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";

// Phần dùng chung của 2 biểu đồ + heatmap: khung thẻ, hộp chú thích khi rê, mốc trục dọc theo triệu

type ChartCardProps = {
  title: string;
  /** Dòng phụ; null ⇒ khung chờ. */
  subtitle: string | null;
  children: React.ReactNode;
  className?: string;
};

/** Thẻ biểu đồ: tiêu đề, dòng phụ, nội dung. */
export function ChartCard({ title, subtitle, children, className }: ChartCardProps) {
  return (
    <Card className={cn("flex min-w-0 flex-col gap-2.5 px-4 py-3.5 lg:px-4.5 lg:py-4", className)}>
      <div className="flex flex-col gap-0.5">
        <h2 className="text-sm font-bold sm:text-base">{title}</h2>
        {subtitle === null ? (
          <Skeleton className="h-4 w-64 max-w-full" />
        ) : (
          <p className="text-xs text-muted">{subtitle}</p>
        )}
      </div>
      {children}
    </Card>
  );
}

/** Hộp chữ khi rê chuột vào điểm / cột. */
export function ChartTip({ text }: { text: string }) {
  return (
    <div className={cn(`
      rounded-lg bg-foreground px-2.5 py-1.5 text-xs font-semibold text-surface tabular-nums
      shadow-card
    `)}>
      {text}
    </div>
  );
}

/** Vùng cuộn kéo được: con trỏ bàn tay; đang kéo ⇒ không chọn chữ, ẩn hộp chú thích khi rê. */
export const dragScrollClass = (isScrollable: boolean, isDragging: boolean) =>
  cn(isScrollable && "cursor-grab", isDragging && `
    cursor-grabbing select-none
    [&_.recharts-tooltip-wrapper]:invisible
  `);

/** Chiều cao vùng vẽ theo cỡ màn (biểu đồ và khung chờ dùng chung ⇒ tải xong không nhảy). */
export const CHART_HEIGHT = "h-56 sm:h-64 2xl:h-72";

/** Khung chờ đúng chiều cao vùng vẽ (heatmap truyền chiều cao riêng). */
export function ChartSkeleton({ className = CHART_HEIGHT }: { className?: string }) {
  return <Skeleton className={cn("w-full rounded-lg", className)} />;
}

const STEPS_M = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000];

/** Mốc trục dọc tròn theo triệu (0, 5 tr, 10 tr…), ≤ 5 mốc, đỉnh cao hơn giá trị lớn nhất một chút. */
export function millionTicks(maxValue: number) {
  const max = Math.max(maxValue * 1.1, 1_000_000);
  const step = (STEPS_M.find((s) => Math.ceil(max / (s * 1_000_000)) <= 4) ?? 1000) * 1_000_000;
  const top = Math.ceil(max / step) * step;
  return Array.from({ length: top / step + 1 }, (_, i) => i * step);
}

/** Nhãn mốc trục dọc: "0", "5 tr". */
export const millionAxisLabel = (v: number) => (v === 0 ? "0" : `${v / 1_000_000} tr`);

/** Màu dùng trong SVG (thuộc tính fill/stroke nhận var()). */
export const CHART_COLOR = {
  primary: "var(--primary)",
  soft: "var(--primary-softer)",
  grid: "var(--border)",
  axis: "var(--muted)",
  average: "var(--accent-fg)",
  danger: "var(--danger)",
  text: "var(--foreground)",
  surface: "var(--surface)",
} as const;
