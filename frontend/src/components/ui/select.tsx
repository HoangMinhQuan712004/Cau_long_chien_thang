import { cn } from "@/lib/cn";

type SelectProps = React.SelectHTMLAttributes<HTMLSelectElement>;

/** Danh sách chọn 1 (select gốc) cùng kiểu với ô nhập. */
export function Select({ className = "", children, ...props }: SelectProps) {
  return (
    <select
      className={cn(
        `
          h-11 w-full rounded-lg border border-border-strong bg-surface px-3 text-base focus-ring
          disabled:cursor-not-allowed disabled:bg-background disabled:text-muted
          aria-invalid:border-danger
          sm:h-9.5 sm:text-sm
        `,
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
}
