"use client";

import { useEffect, useRef, useState } from "react";

/** Kéo quá ngưỡng này (px) mới tính là kéo; ít hơn vẫn là bấm / rê bình thường. */
const DRAG_THRESHOLD = 5;

/**
 * Vùng cuộn ngang: theo dõi còn phần ẩn bên trái / phải (để vẽ bóng mờ, bật con trỏ "grab")
 * và cho bấm giữ chuột rồi kéo để cuộn. Chỉ chuột: điện thoại / bút vẫn vuốt cuộn sẵn của trình duyệt
 * (không chặn vuốt dọc trang). Thanh cuộn và phím ← → (khi vùng được focus) vẫn dùng được.
 */
export function useDragScroll<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  // Phần đã cuộn + bề rộng khung (vd đặt hộp chú thích ngoài khung cuộn)
  const [view, setView] = useState({ left: false, right: false, scrollLeft: 0, width: 0 });
  const [isDragging, setIsDragging] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () =>
      setView({
        left: el.scrollLeft > 1,
        right: el.scrollLeft + el.clientWidth < el.scrollWidth - 1,
        scrollLeft: el.scrollLeft,
        width: el.clientWidth,
      });
    // Đổi cỡ khung hoặc nội dung (đổi kỳ ⇒ đổi số cột) ⇒ tính lại
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    if (el.firstElementChild) observer.observe(el.firstElementChild);

    let start: { x: number; left: number; id: number } | null = null;
    let dragged = false;
    const onDown = (e: PointerEvent) => {
      if (e.pointerType !== "mouse" || e.button !== 0 || el.scrollWidth <= el.clientWidth) return;
      start = { x: e.clientX, left: el.scrollLeft, id: e.pointerId };
      dragged = false;
    };
    const onMove = (e: PointerEvent) => {
      if (!start || e.pointerId !== start.id) return;
      const dx = e.clientX - start.x;
      if (!dragged && Math.abs(dx) < DRAG_THRESHOLD) return;
      if (!dragged) {
        dragged = true;
        el.setPointerCapture(e.pointerId);
        setIsDragging(true);
      }
      e.preventDefault();
      el.scrollLeft = start.left - dx;
    };
    const onUp = (e: PointerEvent) => {
      if (!start || e.pointerId !== start.id) return;
      start = null;
      if (!dragged) return;
      if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId);
      setIsDragging(false);
    };
    // Vừa kéo xong ⇒ bỏ cú click đi kèm (không bấm nhầm vào cột / ô)
    const onClick = (e: MouseEvent) => {
      if (!dragged) return;
      dragged = false;
      e.stopPropagation();
      e.preventDefault();
    };

    el.addEventListener("scroll", measure, { passive: true });
    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
    el.addEventListener("click", onClick, true);
    return () => {
      observer.disconnect();
      el.removeEventListener("scroll", measure);
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointercancel", onUp);
      el.removeEventListener("click", onClick, true);
    };
  }, []);

  const { left, right, scrollLeft, width } = view;
  return { ref, edges: { left, right }, isScrollable: left || right, isDragging, scrollLeft, width };
}
