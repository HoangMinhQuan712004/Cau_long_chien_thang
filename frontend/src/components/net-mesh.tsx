import { cn } from "@/lib/cn";

// Nền mắt lưới cầu lông dùng chung: banner khu hội viên, banner Tổng quan, Hồ sơ, Đặt sân, footer, các màn đăng nhập.

/** Mắt lưới cầu lông vuông sợi trắng phủ cả banner, mờ dần ở mép trên/dưới (kiểu người dùng chọn 12/11, dùng chung mọi banner). */
export function NetMesh({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn(
        "pointer-events-none absolute -z-10 bg-size-[18px_18px] opacity-[0.12]",
        "bg-[linear-gradient(to_right,var(--color-surface)_1px,transparent_1px),linear-gradient(to_bottom,var(--color-surface)_1px,transparent_1px)]",
        "[mask-image:linear-gradient(to_bottom,transparent,black_35%,black_65%,transparent)]",
        className ?? "inset-0",
      )}
    />
  );
}
