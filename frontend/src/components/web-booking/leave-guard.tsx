"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ConfirmDialog } from "@/components/play-rooms/confirm-dialog";

// T-075 AC11–AC12: đang chờ thanh toán thì hỏi trước khi rời trang QR. Không chặn cứng: chọn "Rời trang" là đi bình thường.
// - Đóng tab / tải lại / gõ địa chỉ khác: hộp của trình duyệt (beforeunload, trình duyệt tự chọn câu chữ).
// - Bấm link trong app (logo, menu…): hộp xác nhận của app kèm thời gian còn lại.

/** Link nội bộ (cùng origin, mở trong tab này, không phải tải file / neo trong trang) ⇒ đường dẫn đích; còn lại null. */
function internalHref(e: MouseEvent): string | null {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return null;
  const a = (e.target as Element | null)?.closest?.("a[href]");
  if (!(a instanceof HTMLAnchorElement) || a.target === "_blank" || a.hasAttribute("download")) return null;
  const url = new URL(a.href, window.location.href);
  if (url.origin !== window.location.origin) return null;
  if (url.pathname === window.location.pathname && url.search === window.location.search) return null; // cùng trang (neo / chính nó)
  return `${url.pathname}${url.search}${url.hash}`;
}

export function LeaveGuard({ active, leftText }: { active: boolean; leftText: string }) {
  const router = useRouter();
  const [target, setTarget] = useState<string | null>(null);

  useEffect(() => {
    if (!active) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = ""; // trình duyệt cũ cần gán để hiện hộp hỏi
    };
    const onClick = (e: MouseEvent) => {
      const href = internalHref(e);
      if (!href) return;
      e.preventDefault();
      e.stopPropagation(); // không để next/link điều hướng trước khi người dùng chọn
      setTarget(href);
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onClick, true); // pha bắt: chạy trước handler của next/link
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onClick, true);
    };
  }, [active]);

  if (!target || !active) return null;
  return (
    <ConfirmDialog
      title="Rời trang?"
      body={<p className="text-ui text-muted">Lượt giữ chỗ vẫn còn {leftText}, bạn có thể quay lại từ màn Đặt sân.</p>}
      cancelLabel="Ở lại"
      confirmLabel="Rời trang"
      onClose={() => setTarget(null)}
      onConfirm={async () => {
        const href = target;
        setTarget(null);
        router.push(href);
        return null;
      }}
    />
  );
}
