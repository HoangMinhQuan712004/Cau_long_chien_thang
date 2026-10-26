"use client";

import { useEffect, useId, useRef } from "react";

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
      className={`m-auto w-[calc(100vw-1.5rem)] rounded-xl border border-border bg-surface p-0 text-foreground shadow-xl backdrop:bg-black/45 ${
        size === "wide" ? "max-w-2xl" : "max-w-md"
      }`}
    >
      {open ? (
        <div className="flex max-h-[calc(100dvh-2rem)] flex-col">
          <div className="flex items-center justify-between gap-4 border-b border-border px-5 py-4">
            <h2 id={titleId} className="text-lg font-bold">
              {title}
            </h2>
            <button
              type="button"
              onClick={() => ref.current?.close()}
              aria-label="Đóng"
              className="-m-1 rounded p-1 text-muted hover:text-foreground"
            >
              ✕
            </button>
          </div>
          <div className="space-y-4 overflow-y-auto px-5 py-4">{children}</div>
          {footer ? (
            <div className="flex flex-wrap justify-end gap-2 border-t border-border px-5 py-3">{footer}</div>
          ) : null}
        </div>
      ) : null}
    </dialog>
  );
}
