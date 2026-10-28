"use client";

import { useEffect, useRef } from "react";
import { dismissToast, useReconnecting, useToasts } from "@/lib/feedback";

const KIND_STYLE = {
  success: "border-l-primary",
  error: "border-l-danger",
  info: "border-l-muted",
} as const;

/** Toast góc phải + lớp phủ "Mất kết nối". Gắn một lần trong layout; dùng top layer để nổi trên cả hộp thoại đang mở. */
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
        className="fixed inset-auto top-4 right-4 m-0 w-[min(24rem,calc(100vw-2rem))] flex-col gap-2 open:flex overflow-visible border-0 bg-transparent p-0"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role={t.kind === "error" ? "alert" : "status"}
            className={`flex items-start gap-3 rounded-lg border border-l-4 border-border bg-surface p-3 text-sm text-foreground shadow-lg ${KIND_STYLE[t.kind]}`}
          >
            <div className="min-w-0 flex-1">
              <p className="font-semibold">{t.title}</p>
              {t.sub ? <p className="mt-0.5 text-xs text-muted">{t.sub}</p> : null}
            </div>
            <button
              type="button"
              onClick={() => dismissToast(t.id)}
              aria-label="Đóng thông báo"
              className="-m-1 rounded p-1 text-muted hover:text-foreground"
            >
              ✕
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
