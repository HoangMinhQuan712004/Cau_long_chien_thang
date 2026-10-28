import { cn } from "@/lib/cn";
type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  /** Rộng hết khung, cao 44px trên điện thoại / 42px từ sm (nút chính của form); không `block` thì 38px từ sm. */
  block?: boolean;
  /** Đang xử lý: khóa nút (chặn bấm lặp); chữ trên nút do nơi gọi đổi ("Đang đăng nhập…"). */
  loading?: boolean;
  /** `primary`: nút chính nền xanh; `secondary`: nền trắng viền xanh (hành động phụ). */
  variant?: keyof typeof VARIANT_CLASS;
};

const VARIANT_CLASS = {
  primary: "bg-primary text-surface enabled:hover:bg-primary-hover",
  secondary: "border border-primary bg-surface enabled:hover:bg-primary-softer",
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
          inline-grid place-items-center rounded-lg px-4 text-ui font-semibold focus-ring
          transition-colors
          disabled:cursor-not-allowed disabled:opacity-45
        `,
        VARIANT_CLASS[variant],
        // Điện thoại cao 44px (vùng chạm); máy tính nút thường cao bằng ô nhập
        block ? "h-11 w-full sm:h-10.5" : "h-11 sm:h-9.5",
        className,
      )}
      {...props}
    />
  );
}
