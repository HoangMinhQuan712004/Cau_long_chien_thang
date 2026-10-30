import { cn } from "@/lib/cn";
type CardProps = React.HTMLAttributes<HTMLDivElement> & {
  /** Dưới sm bỏ viền/nền/bóng (khung chứa danh sách thẻ: tránh thẻ lồng trong thẻ, dùng hết bề ngang). */
  bareOnMobile?: boolean;
};

export function Card({ className = "", bareOnMobile = false, ...props }: CardProps) {
  return (
    <div
      className={cn(
        bareOnMobile ? "sm:rounded-card sm:border sm:bg-surface sm:shadow-card" : `
          rounded-card border bg-surface shadow-card
        `,
        className,
      )}
      {...props}
    />
  );
}
