"use client";

import { useEffect, useState } from "react";
import { Modal } from "@/components/ui/modal";

/**
 * Cảnh báo rời trang khi còn thay đổi chưa lưu: đóng tab / tải lại (beforeunload)
 * và bấm liên kết nội bộ (hiện hộp thoại "Rời trang?"). Next App Router không có hook chặn đổi route nên bắt ở cấp liên kết.
 */
export function UnsavedGuard({ dirty }: { dirty: boolean }) {
  const [target, setTarget] = useState<string | null>(null);

  useEffect(() => {
    if (!dirty) return;
    const beforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!a || a.target === "_blank" || a.hasAttribute("download")) return;
      const url = new URL(a.href, window.location.href);
      if (url.origin !== window.location.origin) return;
      if (url.pathname === window.location.pathname && url.search === window.location.search) return;
      e.preventDefault();
      e.stopPropagation();
      setTarget(url.pathname + url.search + url.hash);
    };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", onClick, true); // pha capture: chạy trước bộ điều hướng của next/link
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", onClick, true);
    };
  }, [dirty]);

  return (
    <Modal
      open={target !== null}
      onClose={() => setTarget(null)}
      title="Rời trang?"
      footer={
        <>
          <button type="button" onClick={() => setTarget(null)} className="rounded-md border border-border px-4 py-2 text-sm">
            Ở lại
          </button>
          <button
            type="button"
            onClick={() => {
              const to = target;
              setTarget(null);
              if (to) window.location.assign(to); // tải mới để bỏ hẳn bản nháp và tắt cảnh báo beforeunload
            }}
            className="rounded-md bg-danger px-4 py-2 text-sm font-medium text-primary-fg"
          >
            Rời trang
          </button>
        </>
      }
    >
      <p className="text-sm">Bạn có thay đổi chưa lưu. Rời trang sẽ mất các thay đổi này.</p>
    </Modal>
  );
}
