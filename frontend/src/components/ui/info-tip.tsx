import { useId } from "react";
import { cn } from "@/lib/cn";
import { IconButton } from "./icon-button";
import { InfoIcon } from "./icons";

type InfoTipProps = {
  /** Câu giải thích hiện khi rê chuột / chạm (focus). */
  text: string;
  /** Tên nút cho trình đọc màn hình ("Giải thích"). */
  label: string;
  className?: string;
};

/**
 * Biểu tượng (i): rê chuột hoặc chạm (focus) ⇒ hộp chữ giải thích bên dưới. Không gửi gì lên máy chủ.
 * Ẩn bằng display:none (hộp absolute vô hình vẫn làm trang cuộn ngang trên điện thoại).
 */
export function InfoTip({ text, label, className }: InfoTipProps) {
  const id = useId();
  return (
    <span className={cn("group relative inline-flex", className)}>
      {/* title rỗng: không hiện tooltip trình duyệt, dùng hộp chữ riêng bên dưới */}
      <IconButton icon={<InfoIcon />} label={label} tooltip="" aria-describedby={id} />
      <span
        id={id}
        role="tooltip"
        className={cn(`
          absolute top-full left-1/2 z-10 hidden w-60 max-w-[70vw] -translate-x-1/2 rounded-lg
          bg-foreground px-2.5 py-2 text-xs font-normal text-surface shadow-card
          group-focus-within:block
          group-hover:block
        `)}
      >
        {text}
      </span>
    </span>
  );
}
