import { cn } from "@/lib/cn";
import { ClearButton } from "./clear-button";

type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  ref?: React.Ref<HTMLInputElement>;
  /** Nút gắn cuối ô (hiện mật khẩu…), nằm đè mép phải. */
  endSlot?: React.ReactNode;
  /** Icon đầu ô (kính lúp ô tìm), không bấm được. */
  startSlot?: React.ReactNode;
  /** Có ⇒ ô có chữ thì hiện ✕ cuối ô; bấm ⇒ gọi hàm này rồi focus lại ô. */
  onClear?: () => void;
  /** Tên nút ✕ ("Xóa chữ tìm"). */
  clearLabel?: string;
  /** Gọn (màn quản trị): điện thoại cao 40px, khớp nút thường. Mặc định 44px khớp nút chính `block` (màn khách, đăng nhập). */
  compact?: boolean;
};

export function Input({ endSlot: slot, startSlot, onClear, clearLabel = "", compact = false, className = "", ...props }: InputProps) {
  const hasValue = typeof props.value === "string" ? props.value !== "" : Boolean(props.value);
  const endSlot =
    onClear && hasValue ? (
      <ClearButton
        label={clearLabel}
        onClick={(e) => {
          onClear();
          // Đưa con trỏ về ô vừa xóa (ô nằm cùng khung bọc, không cần ref)
          e.currentTarget.closest("[data-input-wrap]")?.querySelector("input")?.focus();
        }}
      />
    ) : (
      slot
    );
  const input = (
    <input
      // Chữ 16px trên điện thoại (iOS không tự phóng to)
      className={cn(
        `
          w-full rounded-lg border border-border-strong bg-surface px-3 text-ellipsis focus-ring
          transition-shadow
          placeholder:text-subtle
          read-only:bg-background read-only:text-muted
          disabled:cursor-not-allowed disabled:bg-background disabled:text-muted
          sm:h-9.5 sm:text-sm
        `,
        // Gọn (quản trị) trên điện thoại: thấp 32px, chữ 12px (người dùng chốt; đánh đổi: Safari iOS tự phóng to khi chạm ô chữ < 16px)
        compact ? "h-8 text-xs" : "h-11 text-base",
        endSlot ? "pr-10" : undefined,
        startSlot ? (compact ? "pl-8.5 sm:pl-10" : "pl-10") : undefined,
        startSlot ? undefined : className,
      )}
      {...props}
    />
  );
  if (!endSlot && !startSlot) return input;

  // Có slot ⇒ `className` (độ rộng…) đặt ở khung bọc
  return (
    <div data-input-wrap className={cn("relative", startSlot ? className : undefined)}>
      {startSlot ? (
        <div className={cn(
          "pointer-events-none absolute inset-y-0 grid place-items-center text-muted",
          compact ? "left-2.5 sm:left-3 [&>svg]:size-4 sm:[&>svg]:size-4.5" : "left-3",
        )}>
          {startSlot}
        </div>
      ) : null}
      {input}
      {endSlot ? <div className="absolute inset-y-0 right-1 grid place-items-center">{endSlot}</div> : null}
    </div>
  );
}
