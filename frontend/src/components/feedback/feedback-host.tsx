"use client";

import { useEffect, useRef } from "react";
import { AlertCircleIcon, CheckCircleIcon, CloseIcon, InfoIcon } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import { dismissToast, useReconnecting, useToasts } from "@/lib/feedback";

const KIND_STYLE = {
  success: "border-l-primary",
  error: "border-l-danger",
  info: "border-l-muted",
} as const;

// Icon đầu toast theo loại (Figma P5e/P5g: ✓ xanh khi thành công) – không chỉ dựa vào màu viền
const KIND_ICON = {
  success: <CheckCircleIcon className="size-4 shrink-0 text-primary sm:size-5" />,
  error: <AlertCircleIcon className="size-4 shrink-0 text-danger sm:size-5" />,
  info: <InfoIcon className="size-4 shrink-0 text-muted sm:size-5" />,
} as const;

// Điện thoại: thành công / thông tin gọn một dòng (cắt "…"); lỗi phải đọc trọn vì nói cách xử lý
const isOneLine = (kind: keyof typeof KIND_STYLE) => kind !== "error";

/** Toast góc dưới bên phải (điện thoại: hẹp ~17rem, mỗi dòng một hàng cắt "…" cho thấp) + lớp phủ "Mất kết nối". Gắn một lần trong layout; dùng top layer để nổi trên cả hộp thoại đang mở. */
export function FeedbackHost() {
  const toasts = useToasts();
  const reconnecting = useReconnecting();
  const toastBox = useRef<HTMLDivElement>(null);
  const overlay = useRef<HTMLDivElement>(null);

  // Mỗi lần có toast mới: đưa popover lên lại đỉnh top layer (nổi trên <dialog> vừa mở).
  useEffect(() => {
    const el = toastBox.current;
    if (!el || !el.showPopover) return;
    if (toasts.length) {
      if (el.matches(":popover-open")) el.hidePopover();
      el.showPopover();
    } else if (el.matches(":popover-open")) {
      el.hidePopover();
    }
  }, [toasts]);

  useEffect(() => {
    const el = overlay.current;
    if (!el || !el.showPopover) return;
    const open = el.matches(":popover-open");
    if (reconnecting && !open) el.showPopover();
    if (!reconnecting && open) el.hidePopover();
  }, [reconnecting]);

  return (
    <>
      <div
        ref={toastBox}
        popover="manual"
        aria-live="polite"
        data-toast-host
        // Góc dưới phải, chừa thanh home / tai thỏ (safe-area); điện thoại cách mép 12px
        className={cn(`
          fixed inset-auto right-3 bottom-[max(0.75rem,env(safe-area-inset-bottom))] m-0
          w-[min(17rem,calc(100vw-1.5rem))] flex-col gap-2 overflow-visible border-0 bg-transparent p-0
          open:flex
          sm:w-[min(24rem,calc(100vw-2.5rem))]
          sm:right-5 sm:bottom-[max(1.25rem,env(safe-area-inset-bottom))]
        `)}
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role={t.kind === "error" ? "alert" : "status"}
            className={cn(
              `
                flex animate-slide-up gap-2 rounded-lg border border-l-4 border-border bg-surface
                py-1.5 pr-1 pl-2.5 text-xs text-foreground shadow-lg
                sm:gap-3 sm:p-3 sm:text-sm
              `,
              KIND_STYLE[t.kind],
              // Một dòng ⇒ canh giữa; lỗi nhiều dòng (và từ sm) ⇒ icon / nút đóng canh trên
              isOneLine(t.kind) ? "items-center sm:items-start" : "items-start",
            )}
          >
            {KIND_ICON[t.kind]}
            <div className="min-w-0 flex-1">
              <p className={cn("font-semibold", isOneLine(t.kind) && "truncate sm:whitespace-normal")}>{t.title}</p>
              {t.sub ? <p className={cn(
                  "text-[0.6875rem] text-muted sm:mt-0.5 sm:text-xs",
                  isOneLine(t.kind) ? "truncate sm:whitespace-normal" : "wrap-break-word",
                )}>
                  {t.sub}
                </p> : null}
            </div>
            <button
              type="button"
              onClick={() => dismissToast(t.id)}
              aria-label="Đóng thông báo"
              // Hình nhỏ, vùng chạm mở rộng vô hình
              className={cn(`
                relative grid size-6 shrink-0 sm:-my-1 sm:size-7 place-items-center rounded-md text-muted focus-ring
                before:absolute before:-inset-2
                hover:bg-background hover:text-foreground
              `)}
            >
              <CloseIcon size={14} />
            </button>
          </div>
        ))}
      </div>

      <div
        ref={overlay}
        popover="manual"
        role="alertdialog"
        aria-label="Mất kết nối"
        aria-describedby="offline-desc"
        className="fixed inset-0 m-0 h-full w-full max-w-none border-0 bg-black/45 p-4 backdrop-blur-[1px] open:grid open:place-items-center"
      >
        <div className="flex max-w-sm items-start gap-3 rounded-xl border border-border bg-surface p-5 text-foreground shadow-xl">
          <span
            aria-hidden
            className="mt-1 size-4 shrink-0 animate-spin rounded-full border-2 border-border border-t-primary"
          />
          <div>
            <p className="text-base font-bold">Mất kết nối</p>
            <p id="offline-desc" className="mt-1 text-sm leading-relaxed text-muted">
              Mất kết nối. Vui lòng chờ trong giây lát, hệ thống đang thử kết nối lại.
            </p>
          </div>
        </div>
      </div>
    </>
  );
}
