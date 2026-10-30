"use client";

import { useEffect, useId, useRef } from "react";
import { cn } from "@/lib/cn";
import { DrawerResizeHandle, useDrawerWidth } from "./drawer-resize";
import { IconButton } from "./icon-button";
import { CloseIcon } from "./icons";

type Props = {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  /** Có tiêu đề ⇒ hiện đầu ngăn kéo (tiêu đề + ✕); không có ⇒ nội dung tự lo, cần `label` cho trình đọc màn hình. */
  title?: string;
  label?: string;
  closeLabel: string;
  footer?: React.ReactNode;
  /** `right`: chi tiết (Figma P5c); `left`: menu quản trị trên điện thoại. */
  side?: "left" | "right";
  /** Ngăn kéo phải kéo dãn được từ lg (thanh kéo cạnh trái); cần `resizeLabel`. `storageKey` ⇒ nhớ bề rộng. */
  resizable?: boolean;
  resizeLabel?: string;
  storageKey?: string;
};

/** Ngăn kéo cạnh màn hình dùng <dialog> như Modal: khóa nền, bẫy Tab, đóng bằng Esc / bấm nền / ✕. */
export function Drawer({
  open,
  onClose,
  children,
  title,
  label,
  closeLabel,
  footer,
  side = "right",
  resizable = false,
  resizeLabel = "",
  storageKey,
}: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const isResizable = resizable && side === "right";
  const size = useDrawerWidth(isResizable ? storageKey : undefined);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={title ? titleId : undefined}
      aria-label={title ? undefined : label}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) ref.current?.close(); // bấm vùng tối bên ngoài
      }}
      className={cn(
        `
          fixed inset-y-0 h-dvh max-h-dvh max-w-full bg-surface p-0 text-foreground shadow-xl
          transition-transform duration-200
          backdrop:bg-black/45
          motion-reduce:transition-none
        `,
        side === "right"
          ? "right-0 left-auto ml-auto w-full sm:w-lg starting:open:translate-x-full"
          : "right-auto left-0 mr-auto w-72 starting:open:-translate-x-full",
        // Từ lg: rộng theo biến (kéo dãn); dưới lg giữ như cũ
        isResizable && "overflow-visible lg:w-(--drawer-w) lg:max-w-[90vw]",
      )}
      style={isResizable ? ({ "--drawer-w": `${size.width}px` } as React.CSSProperties) : undefined}
    >
      {open && isResizable ? (
        <DrawerResizeHandle width={size.width} onChange={size.set} onReset={size.reset} label={resizeLabel} />
      ) : null}
      {open ? (
        <div className="flex h-full flex-col">
          {title ? (
            <div className={cn(`
              flex items-center justify-between gap-4 px-4 pt-4 pb-3
              sm:px-6 sm:pt-6 sm:pb-4
            `)}>
              <h2 id={titleId} className="text-base font-bold sm:text-lg">
                {title}
              </h2>
              <IconButton
                icon={<CloseIcon />}
                label={closeLabel}
                onClick={() => ref.current?.close()}
                className="-m-1"
              />
            </div>
          ) : null}
          <div className={cn("min-h-0 flex-1 overflow-y-auto overscroll-contain", title && `
            px-4 pb-4
            sm:px-6 sm:pb-6
          `)}>
            {children}
          </div>
          {footer ? (
            <div className={cn(`
              flex flex-wrap justify-end gap-2 border-t px-4 pt-3
              pb-[max(1rem,env(safe-area-inset-bottom))]
              sm:px-6 sm:pb-[max(1.5rem,env(safe-area-inset-bottom))]
            `)}>
              {footer}
            </div>
          ) : null}
        </div>
      ) : null}
    </dialog>
  );
}
