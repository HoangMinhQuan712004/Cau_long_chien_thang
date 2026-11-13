"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

// Chặn rời màn QR khi đơn còn chờ thanh toán: bấm link trong web (kể cả nút ‹ app bar khu hội viên, menu dưới) ⇒ hỏi trước;
// đóng tab / tải lại ⇒ hộp mặc định của trình duyệt. Nút Back của trình duyệt không chặn (App Router không chặn tin cậy được).

/** `active` = còn chờ tiền. Trả `asking` (đang hỏi) + `stay` / `leave` cho hộp thoại. */
export function useLeaveGuard(active: boolean) {
  const router = useRouter();
  const [target, setTarget] = useState<string | null>(null);
  const activeRef = useRef(active);
  useEffect(() => {
    activeRef.current = active;
  }, [active]);

  useEffect(() => {
    if (!active) return;
    // Pha capture ở document chạy trước React (gắn ở root) ⇒ chặn được cả onClick của <Link>
    const onClick = (e: MouseEvent) => {
      if (!activeRef.current || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as Element | null)?.closest?.("a[href]");
      if (!(a instanceof HTMLAnchorElement) || a.target === "_blank" || a.hasAttribute("download")) return;
      const url = new URL(a.href, location.href);
      if (url.origin !== location.origin || url.pathname === location.pathname) return;
      e.preventDefault();
      e.stopPropagation();
      setTarget(url.pathname + url.search + url.hash);
    };
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    document.addEventListener("click", onClick, true);
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      document.removeEventListener("click", onClick, true);
      window.removeEventListener("beforeunload", onBeforeUnload);
    };
  }, [active]);

  return {
    asking: target !== null,
    stay: () => setTarget(null),
    leave: () => {
      const to = target;
      setTarget(null);
      if (to) router.push(to);
    },
  };
}
