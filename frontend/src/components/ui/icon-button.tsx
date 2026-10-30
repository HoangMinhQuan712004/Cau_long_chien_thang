import { cn } from "@/lib/cn";

type IconButtonProps = Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "children" | "aria-label"> & {
  icon: React.ReactNode;
  /** Tên đầy đủ cho trình đọc màn hình, nên kèm đối tượng (vd "Xem chi tiết: Nguyễn Văn A"). */
  label: string;
  /** Gợi ý khi rê chuột (thường chỉ tên hành động); mặc định = `label`. */
  tooltip?: string;
  variant?: keyof typeof VARIANT;
};

const VARIANT = {
  default: "text-muted focus-ring hover:bg-primary-soft/60 hover:text-primary",
  // Nút xóa: nền đỏ nhạt, không lẫn nền xanh
  danger: "text-muted focus-ring hover:bg-danger-soft hover:text-danger",
  // Có viền như nút phụ (đứng riêng, cần nhìn ra là nút)
  outline: "border border-primary bg-surface text-primary focus-ring hover:bg-primary-soft/60",
  // Trên nền xanh đậm (header quản trị)
  inverse: "text-sidebar-fg focus-ring-inverse hover:bg-sidebar-fg/10",
} as const;

/** Nút chỉ có icon: nền nhạt khi rê, có focus-ring, tên qua aria-label và tooltip qua title. */
export function IconButton({ icon, label, tooltip, variant = "default", className, type = "button", ...props }: IconButtonProps) {
  return (
    <button
      type={type}
      aria-label={label}
      title={tooltip ?? label}
      className={cn(
        `
          grid shrink-0 place-items-center rounded-lg transition-colors
          disabled:pointer-events-none disabled:opacity-50
        `,
        // Cùng cỡ với Button: 32px điện thoại, 34px từ sm; vùng chạm mở rộng vô hình lên ≈44px
        "relative before:absolute sm:[&>svg]:size-4.5",
        "size-8 before:-inset-1.5 sm:size-8.5 [&>svg]:size-3.5",
        VARIANT[variant],
        className,
      )}
      {...props}
    >
      {icon}
    </button>
  );
}
