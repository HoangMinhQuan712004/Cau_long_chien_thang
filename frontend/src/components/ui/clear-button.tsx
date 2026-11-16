import { cn } from "@/lib/cn";
import { CloseIcon } from "./icons";

/** Hình ✕ dùng chung; vòng tròn chỉ hiện khi `group` của phần tử cha được rê / focus. */
function ClearMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        `
          grid size-5 shrink-0 place-items-center rounded-full text-primary-hover transition-colors
          group-hover:bg-primary/20
          group-focus-visible:bg-primary/20 group-focus-visible:ring-2
          group-focus-visible:ring-primary
        `,
        className,
      )}
    >
      <CloseIcon size={12} />
    </span>
  );
}

type ClearButtonProps = {
  /** Tên cho trình đọc màn hình và gợi ý khi rê ("Xóa chữ tìm", "Bỏ lọc Hạng"). */
  label: string;
  onClick: (e: React.MouseEvent<HTMLButtonElement>) => void;
  className?: string;
};

/** Nút ✕ "xóa giá trị" dùng chung (ô tìm, ô lọc): vùng chạm cao hết ô, hình là vòng tròn nhỏ. Không dùng cho nút đóng popup. */
export function ClearButton({ label, onClick, className }: ClearButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      // Vùng chạm mở rộng vô hình theo chiều dọc (ngang đã đủ, không lấn ô bên cạnh); cha có position nên before bám theo nút
      className={cn(`
        group grid h-full w-11 place-items-center outline-none
        before:absolute before:inset-x-0 before:-inset-y-1.5
        sm:w-9
      `, className)}
    >
      <ClearMark />
    </button>
  );
}
