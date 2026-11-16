"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useAnchoredPopover } from "@/hooks/use-anchored-popover";
import { cn } from "@/lib/cn";
import { IconButton } from "./icon-button";
import { MoreVerticalIcon } from "./icons";

export type MenuAction = {
  label: string;
  /** Chữ ngắn cho chỗ hẹp (vd nút chính trên điện thoại: "Thêm"). */
  shortLabel?: string;
  icon?: React.ReactNode;
  /** Ở đầu trang / hàng tab: chỉ hiện chữ trơn (không khung, không icon), nổi lên khi rê chuột. */
  plain?: boolean;
  /** Thao tác nguy hiểm (vd Khóa): chữ đỏ trong menu. */
  danger?: boolean;
  onClick: () => void;
};

type ActionMenuProps = {
  /** Tên nút ⋯ cho trình đọc màn hình ("Thao tác khác"). */
  label: string;
  items: readonly MenuAction[];
  /** Nút ⋯ có viền (đứng riêng ở đầu trang); mặc định không viền (trong dòng bảng). */
  outline?: boolean;
  className?: string;
};

/**
 * Nút ⋯ mở menu thao tác (mẫu ARIA menu button): ↑↓ Home End di chuyển, Enter chọn, Esc/Tab đóng. Nổi ở top layer.
 * Điện thoại: menu gọn (hàng 40px, icon 16px, ôm nội dung, không rộng quá màn − 1rem); từ sm hàng 36px.
 */
export function ActionMenu({ label, items, outline = false, className }: ActionMenuProps) {
  const menuId = useId();
  const [isOpen, setIsOpen] = useState(false);
  const [focusIndex, setFocusIndex] = useState(0);
  const anchorRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const close = (refocus = true) => {
    setIsOpen(false);
    if (refocus) anchorRef.current?.querySelector("button")?.focus();
  };
  const place = useAnchoredPopover({
    isOpen,
    anchorRef,
    popoverRef: menuRef,
    itemCount: items.length,
    onDismiss: () => setIsOpen(false),
    align: "end",
  });

  // Mở ⇒ focus thật vào mục (menu dùng focus thật, khác listbox)
  useEffect(() => {
    if (isOpen) menuRef.current?.querySelectorAll<HTMLElement>("[role=menuitem]")[focusIndex]?.focus();
  }, [isOpen, focusIndex]);

  const open = (index: number) => {
    setFocusIndex(index);
    setIsOpen(true);
  };

  function onMenuKey(e: React.KeyboardEvent) {
    const last = items.length - 1;
    const keys: Record<string, number> = { ArrowDown: (focusIndex + 1) % items.length, ArrowUp: (focusIndex - 1 + items.length) % items.length, Home: 0, End: last };
    if (e.key in keys) {
      e.preventDefault();
      setFocusIndex(keys[e.key]);
    } else if (e.key === "Escape") {
      // Chỉ đóng menu, không đóng popup chứa nó
      e.preventDefault();
      e.stopPropagation();
      close();
    } else if (e.key === "Tab") close(false);
  }

  return (
    <div ref={anchorRef} className={className}>
      <IconButton
        icon={<MoreVerticalIcon />}
        label={label}
        variant={outline ? "outline" : "default"}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-controls={menuId}
        onClick={() => (isOpen ? close(false) : open(0))}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            open(e.key === "ArrowDown" ? 0 : items.length - 1);
          }
        }}
      />
      {isOpen ? (
        <div
          ref={menuRef}
          id={menuId}
          role="menu"
          aria-label={label}
          popover="manual"
          onKeyDown={onMenuKey}
          style={place ? { position: "fixed", inset: "auto", ...place } : { visibility: "hidden" }}
          className={cn(
            `
              z-50 m-0 flex max-w-[calc(100vw-1rem)] min-w-40 animate-scale-in flex-col rounded-lg
              border bg-surface p-1 shadow-card
              sm:min-w-48
            `,
            place?.bottom !== undefined ? "origin-bottom-right" : "origin-top-right",
          )}
        >
          {items.map((item, i) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              tabIndex={i === focusIndex ? 0 : -1}
              onClick={() => {
                close();
                item.onClick();
              }}
              className={cn(`
                flex min-h-10 items-center gap-2 rounded-md px-3 text-left text-sm font-medium
                whitespace-nowrap outline-none
                hover:bg-primary-soft/60
                focus-visible:bg-primary-soft/60
                sm:min-h-9 sm:gap-2.5
                [&_svg]:size-4
                sm:[&_svg]:size-4.5
              `, item.danger && "text-danger")}
            >
              {item.icon ? <span aria-hidden className={cn("shrink-0", item.danger ? "text-danger" : `
                text-muted
              `)}>{item.icon}</span> : null}
              {item.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
