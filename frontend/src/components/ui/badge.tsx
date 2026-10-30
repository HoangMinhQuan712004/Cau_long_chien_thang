import { cn } from "@/lib/cn";

const VARIANT_CLASS = {
  // Hoạt động / thành công
  success: "bg-primary-soft text-primary-hover",
  // Loại "Hội viên" (xanh dương)
  info: "bg-info-soft text-info",
  // Hồ sơ tạm / chờ xử lý
  warning: "bg-accent-soft text-accent-fg",
  // Ngừng / không áp dụng
  neutral: "bg-border text-muted",
  danger: "bg-danger-soft text-danger",
} as const;

type BadgeProps = React.HTMLAttributes<HTMLSpanElement> & {
  variant?: keyof typeof VARIANT_CLASS;
};

/** Nhãn trạng thái bo tròn (Figma `Badge trạng thái` 192:3942): chữ 12px đậm, màu theo ý nghĩa. */
export function Badge({ variant = "neutral", className, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        `
          inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold
          whitespace-nowrap
        `,
        VARIANT_CLASS[variant],
        className,
      )}
      {...props}
    />
  );
}
