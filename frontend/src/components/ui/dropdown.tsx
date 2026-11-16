"use client";

import { useEffect, useId, useRef } from "react";
import { useAnchoredPopover } from "@/hooks/use-anchored-popover";
import { useGroupCollapse } from "@/hooks/use-group-collapse";
import { useListbox } from "@/hooks/use-listbox";
import { cn } from "@/lib/cn";
import { ClearButton } from "./clear-button";
import { DropdownGroup } from "./dropdown-group";
import { CheckIcon, ChevronDownIcon } from "./icons";

export type SelectOption = {
  value: string;
  label: string;
  /** Tên nhóm: mục đầu của mỗi nhóm có tiêu đề nhóm phía trên (chỉ là tiêu đề, không chọn được). */
  group?: string;
};

type DropdownProps = {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly SelectOption[];
  /** Dòng đầu chưa chọn (giá trị rỗng), như Select. */
  placeholder?: string;
  "aria-label"?: string;
  /** Chữ trên nút khi đóng (vd "Hạng: Khá"); mặc định là nhãn của mục đang chọn. */
  renderValue?: (option: SelectOption | undefined) => React.ReactNode;
  /** Đang lọc (khác "Tất cả") ⇒ ô tô màu; kèm `onClear` thì có nút ✕ bỏ lọc thay cho mũi tên. */
  active?: boolean;
  onClear?: () => void;
  /** Tên nút ✕ cho trình đọc màn hình ("Bỏ lọc Hạng"). */
  clearLabel?: string;
  /** Gợi ý khi rê chuột (vd nhãn đầy đủ khi chữ bị cắt "…"). */
  title?: string;
  /** "tree": nhóm là cha (chữ đậm, bấm để thu gọn / mở), mục con thụt vào có đường kẻ dọc nối như cây thư mục. */
  variant?: "default" | "tree";
  className?: string;
};

/**
 * Ô chọn tự vẽ thay <select> (màu mục được trỏ của hệ điều hành không đổi được bằng CSS).
 * Danh sách nổi ở top layer (Popover API) hoặc fixed nên không bị Modal/Drawer cắt; gần đáy màn hình thì lật lên.
 */
export function Dropdown({
  id,
  value,
  onChange,
  options,
  placeholder,
  renderValue,
  active = false,
  onClear,
  clearLabel,
  title,
  variant = "default",
  className,
  ...aria
}: DropdownProps) {
  const autoId = useId();
  const listId = `${autoId}-list`;
  const buttonRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const optionId = (i: number) => `${autoId}-opt-${i}`;
  const all = placeholder !== undefined ? [{ value: "", label: placeholder }, ...options] : options;
  const selectedIndex = all.findIndex((o) => o.value === value);
  // Bàn phím chỉ đi qua mục đang hiện (nhóm thu gọn ⇒ bỏ qua con); chỉ số của useListbox tính trên `visible`
  const groups = useGroupCollapse(all);
  const visible = groups.visible;
  const box = useListbox({
    labels: visible.map((i) => all[i].label),
    selectedIndex: visible.indexOf(selectedIndex),
    onSelect: (v) => {
      if (all[visible[v]].value !== value) onChange(all[visible[v]].value);
    },
  });
  // Đóng danh sách ⇒ lần mở sau các nhóm lại mở hết (mục đang chọn luôn thấy được)
  if (!box.isOpen && groups.hasCollapsed) groups.reset();
  /** Mục đang trỏ, chỉ số trong `all`. */
  const activeAt = visible[box.activeIndex] ?? -1;
  const place = useAnchoredPopover({ isOpen: box.isOpen, anchorRef: buttonRef, popoverRef: listRef, itemCount: all.length, onDismiss: box.close });

  // Mục đang trỏ luôn nằm trong vùng nhìn thấy
  useEffect(() => {
    // Tìm theo id (danh sách có thể xen tiêu đề nhóm nên không dùng vị trí con)
    if (box.isOpen) document.getElementById(`${autoId}-opt-${activeAt}`)?.scrollIntoView({ block: "nearest" });
  }, [autoId, box.isOpen, activeAt]);

  const selected = all[selectedIndex];
  const hasClear = active && onClear !== undefined;
  const isTree = variant === "tree";
  const toggleGroup = (group: string) => {
    // Mục đang trỏ bị ẩn theo nhóm ⇒ bỏ trỏ (↓ đi lại từ đầu)
    box.setActiveIndex(groups.toggle(group).indexOf(activeAt));
  };

  return (
    <div className={cn("relative", className)}>
      <button
        ref={buttonRef}
        id={id}
        type="button"
        role="combobox"
        aria-label={aria["aria-label"]}
        aria-haspopup="listbox"
        aria-expanded={box.isOpen}
        aria-controls={listId}
        aria-activedescendant={box.isOpen && activeAt >= 0 ? optionId(activeAt) : undefined}
        title={title}
        onClick={() => (box.isOpen ? box.close() : box.open())}
        onKeyDown={box.onKeyDown}
        className={cn(
          `
            relative flex h-8 w-full items-center gap-1.5 border px-2.5 text-left focus-ring
            transition-colors
            before:absolute before:inset-x-0 before:-inset-y-1.5
            sm:gap-2 sm:px-3
          `,
          // Cao bằng Input gọn (32px điện thoại, vùng chạm mở rộng vô hình lên 44px qua before); chữ nhỏ (nút, không phải ô gõ nên iOS không tự phóng to)
          "rounded-lg text-xs sm:h-9.5 sm:text-sm",
          active ? "border-primary bg-primary-softer font-medium text-primary" : `
            border-border-strong bg-surface
          `,
          // Chừa chỗ cho nút ✕ đặt đè bên phải
          hasClear && "pr-11 sm:pr-9",
        )}
      >
        <span className="min-w-0 flex-1 truncate">{renderValue ? renderValue(selected) : selected?.label}</span>
        {hasClear ? null : (
          <ChevronDownIcon size={16} className={cn(`
            size-3.5 shrink-0 text-muted transition-transform
            sm:size-4
          `, box.isOpen && `rotate-180`)} />
        )}
      </button>
      {hasClear ? (
        // Nút riêng ngoài combobox (không lồng button): bỏ lọc, không mở danh sách
        <ClearButton
          label={clearLabel ?? ""}
          onClick={() => {
            onClear?.();
            buttonRef.current?.focus();
          }}
          className="absolute inset-y-0 right-0"
        />
      ) : null}
      {box.isOpen ? (
        <ul
          ref={listRef}
          id={listId}
          role="listbox"
          popover="manual"
          aria-label={aria["aria-label"]}
          tabIndex={-1}
          style={place ? { position: "fixed", inset: "auto", ...place } : { visibility: "hidden" }}
          className={cn(
            `
              z-50 m-0 max-h-72 max-w-80 animate-scale-in overflow-y-auto overscroll-contain
              rounded-lg border bg-surface p-1 text-xs text-foreground shadow-card
              sm:text-sm
            `,
            place?.bottom !== undefined ? "origin-bottom" : "origin-top",
          )}
        >
          {all.map((o, i) => [
            o.group && o.group !== all[i - 1]?.group ? (
              <DropdownGroup
                key={`group-${o.group}`}
                label={o.group}
                isTree={isTree}
                isCollapsed={groups.isCollapsed(o.group)}
                onToggle={() => toggleGroup(o.group ?? "")}
              />
            ) : null,
            o.group && groups.isCollapsed(o.group) ? null : <li
              key={o.value}
              id={optionId(i)}
              role="option"
              aria-selected={i === selectedIndex}
              // Giữ focus ở nút (mẫu activedescendant)
              onMouseDown={(e) => e.preventDefault()}
              onMouseMove={() => activeAt !== i && box.setActiveIndex(visible.indexOf(i))}
              onClick={() => box.choose(visible.indexOf(i))}
              className={cn(
                "flex cursor-pointer items-center gap-2 rounded-md px-2.5 sm:px-3",
                // Cây: cao 44px trên điện thoại (vùng chạm); con thụt vào, viền trái liền nhau thành đường kẻ dọc dưới chevron nhóm
                isTree ? "min-h-11 sm:min-h-9" : "min-h-9",
                isTree && o.group && "ml-4.5 rounded-l-none border-l sm:ml-5",
                i === activeAt && "bg-primary-soft/60",
                i === selectedIndex && "font-semibold text-primary",
              )}
            >
              <span className="min-w-0 flex-1">{o.label}</span>
              {i === selectedIndex ? <CheckIcon size={16} className="shrink-0" /> : null}
            </li>,
          ])}
        </ul>
      ) : null}
    </div>
  );
}
