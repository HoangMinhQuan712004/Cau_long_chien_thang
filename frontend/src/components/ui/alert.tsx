import { cn } from "@/lib/cn";
import { AlertCircleIcon, InfoIcon } from "./icons";

type AlertProps = {
  variant?: "error" | "info";
  children: React.ReactNode;
  className?: string;
};

// Tên variant theo prototype (.banner.error / .banner.info)
const VARIANT_CLASS = {
  error: "bg-danger-soft text-danger",
  info: "border bg-primary-softer text-muted",
} as const;

export function Alert({ variant = "error", children, className = "" }: AlertProps) {
  const Icon = variant === "error" ? AlertCircleIcon : InfoIcon;
  return (
    <div
      // Lỗi đọc ngay; thông tin đọc khi rảnh
      role={variant === "error" ? "alert" : "status"}
      className={cn(
        "flex items-start gap-2 rounded-lg px-3 py-2.5 text-ui",
        VARIANT_CLASS[variant],
        className,
      )}
    >
      <Icon className="shrink-0" />
      {/* div (không p): nội dung có thể là danh sách / nút */}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
