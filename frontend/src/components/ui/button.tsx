import { cn } from "@/lib/cn";
type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  /** Rộng hết khung, cao 44px trên điện thoại / 42px từ sm (nút chính của form); không `block` thì 38px từ sm. */
  block?: boolean;
  /** Đang xử lý: khóa nút (chặn bấm lặp); chữ trên nút do nơi gọi đổi ("Đang đăng nhập…"). */
  loading?: boolean;
  /** `primary`: nút chính nền xanh; `secondary`: nền trắng viền xanh (hành động phụ); `danger`: nền đỏ (xóa). */
  variant?: keyof typeof VARIANT_CLASS;
};

const VARIANT_CLASS = {
  // Đang nhấn: nút chính co nhẹ (tắt khi giảm chuyển động), nút phụ nền đậm hơn một nấc
  primary: "bg-primary text-surface enabled:hover:bg-primary-hover enabled:active:scale-[0.98] motion-reduce:enabled:active:scale-100",
  secondary: "border border-primary bg-surface enabled:hover:bg-primary-soft/60 enabled:active:bg-primary-soft",
  // Nút nhẹ không viền (vd "Xóa lọc" cuối thanh lọc)
  ghost: "text-muted enabled:hover:bg-primary-soft/60 enabled:hover:text-primary",
  // Hành động không hoàn tác được (Xóa) – chỉ dùng trong hộp xác nhận
  danger: "bg-danger text-surface enabled:hover:bg-danger/90",
  // Nút hành động chính của khu hội viên (T-028): vàng, chữ tối, in hoa đậm. Mỗi màn chỉ một nút.
  cta: "bg-cta font-bold tracking-wide text-cta-fg uppercase enabled:hover:bg-cta-hover enabled:active:scale-[0.98] motion-reduce:enabled:active:scale-100",
} as const;

/** Nút (prototype `.btn.primary` / `.btn.secondary`). */
export function Button({
  variant = "primary",
  block = false,
  loading = false,
  disabled,
  className = "",
  ...props
}: ButtonProps) {
  return (
    <button
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        `
          inline-flex items-center justify-center rounded-lg font-semibold focus-ring
          transition-colors
          disabled:cursor-not-allowed disabled:opacity-45
        `,
        VARIANT_CLASS[variant],
        // Nút chính form (block) cao 44px. Mọi nút thường chung một cỡ gọn: điện thoại 32px (vùng chạm vô hình 44px), từ sm 34px
        block ? "h-11 w-full gap-2 px-4 text-ui sm:h-10.5" : `
          relative h-8 gap-1 px-2.5 text-xs
          before:absolute before:inset-x-0 before:-inset-y-1.5
          sm:h-8.5 sm:gap-2 sm:px-4 sm:text-ui
          [&>svg]:size-3.5
          sm:[&>svg]:size-4.5
        `,
        className,
      )}
      {...props}
    />
  );
}
