import { cn } from "@/lib/cn";
import { ChevronDownIcon } from "./icons";

type Props = {
  label: string;
  /** Dạng cây: tiêu đề là nút thu gọn / mở nhóm (vẫn không chọn làm giá trị được). */
  isTree: boolean;
  isCollapsed: boolean;
  onToggle: () => void;
};

/** Tiêu đề nhóm trong danh sách của Dropdown (không phải option: phím ↑↓ bỏ qua). */
export function DropdownGroup({ label, isTree, isCollapsed, onToggle }: Props) {
  if (!isTree) {
    return (
      <li role="presentation" className={cn(`
        px-2.5 pt-2 pb-1 text-label font-semibold tracking-wide text-muted uppercase
        sm:px-3
      `)}>
        {label}
      </li>
    );
  }
  return (
    <li role="presentation">
      {/* tabIndex -1 + chặn mousedown: focus ở lại ô chọn (mẫu activedescendant) */}
      <button
        type="button"
        tabIndex={-1}
        aria-expanded={!isCollapsed}
        onMouseDown={(e) => e.preventDefault()}
        onClick={onToggle}
        className={cn(`
          flex min-h-11 w-full cursor-pointer items-center gap-2 rounded-md px-2.5 text-left
          font-semibold transition-colors
          hover:text-primary
          sm:min-h-9 sm:px-3
        `)}
      >
        <ChevronDownIcon
          size={16}
          className={cn(
            "shrink-0 text-muted transition-transform duration-200 motion-reduce:transition-none",
            isCollapsed && "-rotate-90",
          )}
        />
        <span className="min-w-0 flex-1">{label}</span>
      </button>
    </li>
  );
}
