"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";

// Cao tối đa của danh sách (18rem) và cao mỗi mục, để tính có nên lật lên trên không
const LIST_MAX_PX = 288;
const ITEM_PX = 44;
// Danh sách rộng ít nhất bằng nút (nút có thể hẹp hơn mục dài nhất)
type PopoverPlace = { left?: number; right?: number; minWidth: number; top?: number; bottom?: number };

type Options = {
  isOpen: boolean;
  anchorRef: React.RefObject<HTMLElement | null>;
  popoverRef: React.RefObject<HTMLElement | null>;
  itemCount: number;
  /** Bấm ra ngoài nút và danh sách. */
  onDismiss: () => void;
  /** `end`: canh mép phải với nút (menu ở góc phải màn hình). */
  align?: "start" | "end";
};

/** Danh sách nổi bám theo nút: toạ độ fixed (lật lên khi gần đáy), đưa lên top layer bằng Popover API, bấm ra ngoài thì đóng. */
export function useAnchoredPopover({ isOpen, anchorRef, popoverRef, itemCount, onDismiss, align = "start" }: Options): PopoverPlace | null {
  const [place, setPlace] = useState<PopoverPlace | null>(null);
  const dismiss = useRef(onDismiss);
  useEffect(() => {
    dismiss.current = onDismiss;
  });

  // Đặt danh sách ngay dưới (hoặc trên) nút; theo nút khi cuộn / đổi cỡ
  useLayoutEffect(() => {
    if (!isOpen) return;
    const update = () => {
      const r = anchorRef.current?.getBoundingClientRect();
      if (!r) return;
      const below = window.innerHeight - r.bottom;
      const isUp = below < Math.min(LIST_MAX_PX, itemCount * ITEM_PX) && r.top > below;
      setPlace({
        ...(align === "end" ? { right: document.documentElement.clientWidth - r.right } : { left: r.left }),
        minWidth: r.width, ...(isUp ? { bottom: window.innerHeight - r.top + 4 } : { top: r.bottom + 4 }) });
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [isOpen, itemCount, anchorRef, align]);

  // Đưa lên top layer (nổi trên <dialog>); trình duyệt chưa có Popover API ⇒ vẫn là fixed
  useEffect(() => {
    const list = popoverRef.current;
    if (!isOpen || !list || !("showPopover" in list)) return;
    list.showPopover();
    return () => {
      if (list.matches(":popover-open")) list.hidePopover();
    };
  }, [isOpen, popoverRef]);

  // Bấm ra ngoài ⇒ đóng
  useEffect(() => {
    if (!isOpen) return;
    const onDown = (e: PointerEvent) => {
      const target = e.target as Node;
      if (!anchorRef.current?.contains(target) && !popoverRef.current?.contains(target)) dismiss.current();
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [isOpen, anchorRef, popoverRef]);

  return place;
}
