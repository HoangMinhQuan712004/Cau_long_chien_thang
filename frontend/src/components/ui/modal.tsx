"use client";

import { useEffect, useId, useRef } from "react";
import { cn } from "@/lib/cn";
import { IconButton } from "./icon-button";
import { CloseIcon } from "./icons";

type Props = {
  open: boolean;
  onClose: () => void;
  title: string;
  /** Dòng phụ dưới tiêu đề (vd ngày · giờ của booking), chữ nhỏ màu muted. */
  subtitle?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  /** narrow 28rem · medium 32rem · wide 42rem · large: 32rem, từ md 56rem (popup thông tin booking bố cục ngang). */
  size?: "narrow" | "medium" | "wide" | "large";
  /** Ghi đè kiểu của chân hộp thoại (ví dụ thanh dưới màu xanh ở popup sự kiện, T-028). */
  footerClassName?: string;
  /** Điện thoại: trượt từ đáy, bo góc trên 20 px (khu hội viên). Từ sm: hộp giữa màn như thường. */
  sheet?: boolean;
  /** Dưới md: màn toàn trang (cao hết màn hình, không bo góc); từ md: hộp thoại như thường (T-039). */
  full?: boolean;
};

/** Hộp thoại dùng <dialog> gốc: tự khóa nền, bẫy phím Tab, đóng bằng Esc. */
export function Modal({ open, onClose, title, subtitle, children, footer, size = "narrow", footerClassName, sheet = false, full = false }: Props) {
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
      // Chỉ khi chính dialog này đóng: popup con mở qua portal vẫn nằm trong cây React, sự kiện close của nó đi ngược lên đây
      onClose={(e) => e.target === e.currentTarget && onClose()}
      onClick={(e) => {
        if (e.target === ref.current) ref.current?.close(); // bấm vùng tối bên ngoài
      }}
      className={cn(
        sheet
          ? `
            m-0 mt-auto max-h-[calc(100dvh-2rem)] w-full overflow-hidden rounded-t-[20px] border-0
            bg-surface p-0 text-foreground shadow-xl
            sm:m-auto sm:w-[calc(100vw-1.5rem)] sm:rounded-xl sm:border sm:border-border
          `
          : `
            m-auto max-h-[calc(100dvh-2rem)] w-[calc(100vw-1.5rem)] overflow-hidden rounded-xl
            border border-border bg-surface p-0 text-foreground shadow-xl
          `,
        // Mỗi lần showModal phần tử đổi từ display:none ⇒ animation chạy lại
        "animate-scale-in backdrop:animate-fade-in backdrop:bg-black/45",
        size === "wide" ? "max-w-2xl" : size === "large" ? "max-w-lg md:max-w-4xl" : size === "medium" ? `
          max-w-lg
        ` : `max-w-md`,
        sheet && (size === "large" ? "max-w-none sm:max-w-lg md:max-w-4xl" : size === "medium" ? `
          max-w-none
          sm:max-w-lg
        ` : `max-w-none sm:max-w-md`),
        full && `
          max-md:m-0 max-md:h-dvh max-md:max-h-none max-md:w-full max-md:max-w-none
          max-md:rounded-none max-md:border-0
        `,
      )}
    >
      {open ? (
        // 3 vùng tách hẳn: đầu cố định, thân là vùng cuộn duy nhất, chân cố định (không đè lên nội dung)
        <div className={cn("flex max-h-[calc(100dvh-2rem)] flex-col", full && `
          max-md:h-dvh max-md:max-h-none
        `)}>
          <div className={cn(`
            flex shrink-0 items-center justify-between gap-4 border-b border-border px-5 py-4
          `)}>
            <div className="min-w-0">
              <h2 id={titleId} className="text-lg font-bold">
                {title}
              </h2>
              {subtitle ? <p className="text-ui text-muted">{subtitle}</p> : null}
            </div>
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
            `, footerClassName)}>
              {footer}
            </div>
          ) : null}
        </div>
      ) : null}
    </dialog>
  );
}
