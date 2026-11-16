"use client";

import { useEffect, useRef, useState } from "react";

/** Kéo quá ngưỡng này (px) mới tính là kéo; ít hơn vẫn là bấm / rê bình thường. */
const DRAG_THRESHOLD = 5;
/** Quán tính: mỗi khung hình (~16 ms) vận tốc còn lại bao nhiêu; dưới MIN_SPEED (px/ms) thì dừng. */
const FRICTION = 0.9;
/** Trần vận tốc (px/ms) để vung mạnh cũng chỉ trôi thêm vừa phải (~ nửa màn). */
const MAX_SPEED = 3;
const MIN_SPEED = 0.02;
/** Chỉ lấy các điểm trong 100 ms cuối để tính vận tốc lúc thả chuột. */
const SAMPLE_MS = 100;

type Options = {
  /** "x": chỉ cuộn ngang (mặc định, biểu đồ Báo cáo); "both": ngang + dọc (lưới Đặt sân). */
  axis?: "x" | "both";
  /** Thả chuột khi đang kéo nhanh ⇒ trôi thêm một đoạn rồi dừng (tắt khi người dùng chọn giảm chuyển động). */
  inertia?: boolean;
};

/**
 * Vùng cuộn: theo dõi còn phần ẩn bên trái / phải (để vẽ bóng mờ, bật con trỏ "grab")
 * và cho bấm giữ chuột rồi kéo để cuộn. Chỉ chuột: điện thoại / bút vẫn vuốt cuộn sẵn của trình duyệt
 * (không chặn vuốt dọc trang). Thanh cuộn, Shift + lăn chuột và phím mũi tên vẫn dùng được.
 * Kéo xong thì cú click đi kèm bị bỏ ⇒ không chọn nhầm ô / cột; bấm thả tại chỗ vẫn là click.
 */
export function useDragScroll<T extends HTMLElement>({ axis = "x", inertia = false }: Options = {}) {
  const ref = useRef<T>(null);
  // Phần đã cuộn + bề rộng khung (vd đặt hộp chú thích ngoài khung cuộn)
  const [view, setView] = useState({ left: false, right: false, vertical: false, scrollLeft: 0, width: 0 });
  const [isDragging, setIsDragging] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const both = axis === "both";
    const measure = () =>
      setView({
        left: el.scrollLeft > 1,
        right: el.scrollLeft + el.clientWidth < el.scrollWidth - 1,
        vertical: both && el.scrollHeight > el.clientHeight + 1,
        scrollLeft: el.scrollLeft,
        width: el.clientWidth,
      });
    // Đổi cỡ khung hoặc nội dung (đổi kỳ ⇒ đổi số cột) ⇒ tính lại
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    if (el.firstElementChild) observer.observe(el.firstElementChild);

    const canScroll = () => el.scrollWidth > el.clientWidth || (both && el.scrollHeight > el.clientHeight);
    let start: { x: number; y: number; left: number; top: number; id: number } | null = null;
    let dragged = false;
    let samples: { t: number; x: number; y: number }[] = [];
    let frame = 0;
    const stopGlide = () => cancelAnimationFrame(frame);

    const onDown = (e: PointerEvent) => {
      stopGlide();
      dragged = false;
      if (e.pointerType !== "mouse" || e.button !== 0 || !canScroll()) return;
      start = { x: e.clientX, y: e.clientY, left: el.scrollLeft, top: el.scrollTop, id: e.pointerId };
      samples = [{ t: e.timeStamp, x: e.clientX, y: e.clientY }];
    };
    const onMove = (e: PointerEvent) => {
      if (!start || e.pointerId !== start.id) return;
      const dx = e.clientX - start.x;
      const dy = both ? e.clientY - start.y : 0;
      if (!dragged && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
      if (!dragged) {
        dragged = true;
        el.setPointerCapture(e.pointerId);
        setIsDragging(true);
      }
      e.preventDefault();
      el.scrollLeft = start.left - dx;
      if (both) el.scrollTop = start.top - dy;
      samples.push({ t: e.timeStamp, x: e.clientX, y: e.clientY });
      while (samples.length > 2 && e.timeStamp - samples[0].t > SAMPLE_MS) samples.shift();
    };
    const glide = (vx: number, vy: number) => {
      let last = performance.now();
      const step = (now: number) => {
        const dt = Math.min(now - last, 32);
        last = now;
        el.scrollLeft -= vx * dt;
        el.scrollTop -= vy * dt;
        const k = FRICTION ** (dt / 16);
        vx *= k;
        vy *= k;
        if (Math.hypot(vx, vy) > MIN_SPEED) frame = requestAnimationFrame(step);
      };
      frame = requestAnimationFrame(step);
    };
    const onUp = (e: PointerEvent) => {
      if (!start || e.pointerId !== start.id) return;
      start = null;
      if (!dragged) return;
      if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId);
      setIsDragging(false);
      const first = samples[0];
      const span = e.timeStamp - first.t;
      const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      // Dừng tay trước khi thả (> SAMPLE_MS) ⇒ không trôi
      if (inertia && !calm && e.type === "pointerup" && span > 0 && span <= SAMPLE_MS * 1.5) {
        const cap = (v: number) => Math.max(-MAX_SPEED, Math.min(MAX_SPEED, v));
        glide(cap((e.clientX - first.x) / span), both ? cap((e.clientY - first.y) / span) : 0);
      }
    };
    // Vừa kéo xong ⇒ bỏ cú click đi kèm (không bấm nhầm vào cột / ô)
    const onClick = (e: MouseEvent) => {
      if (!dragged) return;
      dragged = false;
      e.stopPropagation();
      e.preventDefault();
    };
    // Lăn chuột / vuốt trackpad ⇒ dừng trôi (không giành cuộn với người dùng)
    const onWheel = () => stopGlide();

    el.addEventListener("scroll", measure, { passive: true });
    el.addEventListener("wheel", onWheel, { passive: true });
    el.addEventListener("pointerdown", onDown);
    // Di / thả nghe ở window: chuột ra ngoài khung (hoặc mất pointer capture) vẫn kết thúc kéo, không kẹt "grabbing"
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    el.addEventListener("click", onClick, true);
    return () => {
      stopGlide();
      observer.disconnect();
      el.removeEventListener("scroll", measure);
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("pointerdown", onDown);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      el.removeEventListener("click", onClick, true);
    };
  }, [axis, inertia]);

  const { left, right, vertical, scrollLeft, width } = view;
  return { ref, edges: { left, right }, isScrollable: left || right || vertical, isDragging, scrollLeft, width };
}
