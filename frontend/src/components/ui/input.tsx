import { cn } from "@/lib/cn";
type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  ref?: React.Ref<HTMLInputElement>;
  /** Nút gắn cuối ô (hiện mật khẩu…), nằm đè mép phải. */
  endSlot?: React.ReactNode;
};

export function Input({ endSlot, className = "", ...props }: InputProps) {
  const input = (
    <input
      // Điện thoại cao 44px, chữ 16px (iOS không tự phóng to)
      className={cn(
        `
          h-11 w-full rounded-lg border border-border-strong bg-surface px-3 text-base text-ellipsis
          focus-ring transition-shadow
          placeholder:text-subtle
          read-only:bg-background read-only:text-muted
          disabled:cursor-not-allowed disabled:bg-background disabled:text-muted
          sm:h-9.5 sm:text-sm
        `,
        endSlot ? "pr-10" : undefined,
        className,
      )}
      {...props}
    />
  );
  if (!endSlot) return input;

  return (
    <div className="relative">
      {input}
      <div className="absolute inset-y-0 right-1 grid place-items-center">{endSlot}</div>
    </div>
  );
}
