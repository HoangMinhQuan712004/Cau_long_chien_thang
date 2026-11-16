"use client";

import { useEffect, useId, useRef } from "react";
import { cn } from "@/lib/cn";

type Props = {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  className?: string;
};

/**
 * Bảng trượt từ đáy trên điện thoại (bo góc trên 20 px), hộp giữa màn từ lg (T-028 N3).
 * Dùng <dialog> gốc: tự khóa nền, bẫy Tab, Esc để đóng; bấm vùng tối cũng đóng.
 */
export function BottomSheet({ open, onClose, title, children, className }: Props) {
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
        if (e.target === ref.current) ref.current?.close();
      }}
      className={cn(
        `
          m-0 mt-auto max-h-[85dvh] w-full max-w-none animate-slide-up overflow-hidden
          rounded-t-[20px] border-0 bg-surface p-0 text-foreground shadow-xl
          backdrop:animate-fade-in backdrop:bg-black/45
          lg:m-auto lg:max-w-md lg:animate-scale-in lg:rounded-[20px]
        `,
        className,
      )}
    >
      {open ? (
        <div className="flex max-h-[85dvh] flex-col pb-[env(safe-area-inset-bottom)]">
          <div aria-hidden className="
            mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-border-strong
            lg:hidden
          " />
          <h2 id={titleId} className="shrink-0 px-5 pt-3 pb-2 text-base font-bold">
            {title}
          </h2>
          <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">{children}</div>
        </div>
      ) : null}
    </dialog>
  );
}
