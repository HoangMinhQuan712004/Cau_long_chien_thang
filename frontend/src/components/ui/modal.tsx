"use client";

import { useEffect, useId, useRef } from "react";
import { cn } from "@/lib/cn";
import { IconButton } from "./icon-button";
import { CloseIcon } from "./icons";

type Props = {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  size?: "narrow" | "wide";
};

/** Hộp thoại dùng <dialog> gốc: tự khóa nền, bẫy phím Tab, đóng bằng Esc. */
export function Modal({ open, onClose, title, children, footer, size = "narrow" }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) ref.current?.close(); // bấm vùng tối bên ngoài
      }}
      className={cn(
        `
          m-auto max-h-[calc(100dvh-2rem)] w-[calc(100vw-1.5rem)] overflow-hidden rounded-xl border
          border-border bg-surface p-0 text-foreground shadow-xl
        `,
        // Mỗi lần showModal phần tử đổi từ display:none ⇒ animation chạy lại
        "animate-scale-in backdrop:animate-fade-in backdrop:bg-black/45",
        size === "wide" ? "max-w-2xl" : "max-w-md",
      )}
    >
      {open ? (
        // 3 vùng tách hẳn: đầu cố định, thân là vùng cuộn duy nhất, chân cố định (không đè lên nội dung)
        <div className="flex max-h-[calc(100dvh-2rem)] flex-col">
          <div className={cn(`
            flex shrink-0 items-center justify-between gap-4 border-b border-border px-5 py-4
          `)}>
            <h2 id={titleId} className="text-lg font-bold">
              {title}
            </h2>
            <IconButton
              icon={<CloseIcon />}
              label="Đóng"
              onClick={() => ref.current?.close()}
              className="-m-1"
            />
          </div>
          <div className={cn(`
            min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain px-5 pt-5 pb-6
          `)}>{children}</div>
          {footer ? (
            <div className={cn(`
              flex shrink-0 flex-wrap justify-end gap-2 border-t border-border bg-surface px-5 pt-3
              pb-[max(0.75rem,env(safe-area-inset-bottom))]
            `)}>
              {footer}
            </div>
          ) : null}
        </div>
      ) : null}
    </dialog>
  );
}
