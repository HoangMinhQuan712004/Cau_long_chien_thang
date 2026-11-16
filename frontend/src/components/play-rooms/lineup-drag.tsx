"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { SlotRef } from "./lineup";

// Kéo thả bằng pointer events. Chuột / bút: kéo ngay. Cảm ứng: giữ ~0,3 giây rồi kéo (vuốt ngay = cuộn trang,
// chạm nhanh = mở hộp chọn ô như T-027 AC3).

export type DragSource = { kind: "member"; id: number } | { kind: "slot"; ref: SlotRef };
/** `null` = thả ngoài sân. */
export type DropTarget = SlotRef | null;

const THRESHOLD = 6;
/** Cảm ứng: giữ bao lâu thì bắt đầu kéo; nhích quá ngưỡng trước đó = đang cuộn, bỏ kéo. */
const HOLD_MS = 300;
const TOUCH_SLOP = 10;

function slotAt(x: number, y: number): { ref: SlotRef | null; inCourt: boolean } {
  const el = document.elementFromPoint(x, y);
  const slot = el?.closest<HTMLElement>("[data-slot]");
  const inCourt = Boolean(el?.closest("[data-court]"));
  if (!slot) return { ref: null, inCourt };
  const [team, idx] = (slot.dataset.slot ?? "").split("-");
  return { ref: { team: team as SlotRef["team"], idx: Number(idx) }, inCourt };
}

export function useLineupDrag(onDrop: (source: DragSource, target: DropTarget, inCourt: boolean) => void) {
  const [ghost, setGhost] = useState<{ label: string; x: number; y: number } | null>(null);
  const [over, setOver] = useState("");
  // Giữ handler mới nhất cho listener gắn lúc nhấn chuột
  const dropRef = useRef(onDrop);
  useEffect(() => {
    dropRef.current = onDrop;
  });
  // Đang kéo bằng tay: chặn cuộn trang (nếu không trình duyệt cuộn và hủy pointer). Gắn sẵn từ đầu vì
  // listener `touchmove` thêm sau khi chạm có thể không được phép preventDefault.
  const touchDrag = useRef(false);
  useEffect(() => {
    const block = (ev: TouchEvent) => {
      if (touchDrag.current) ev.preventDefault();
    };
    document.addEventListener("touchmove", block, { passive: false });
    return () => document.removeEventListener("touchmove", block);
  }, []);

  const begin = useCallback((e: React.PointerEvent, source: DragSource, label: string) => {
    if (e.button !== 0) return;
    const touch = e.pointerType === "touch";
    const sx = e.clientX;
    const sy = e.clientY;
    let started = false;
    // Cảm ứng chỉ được kéo sau khi giữ đủ lâu
    let armed = !touch;
    const show = (x: number, y: number) => {
      setGhost({ label, x, y });
      const { ref } = slotAt(x, y);
      setOver(ref ? `${ref.team}-${ref.idx}` : "");
    };
    const timer = touch
      ? window.setTimeout(() => {
          armed = true;
          started = true;
          touchDrag.current = true;
          navigator.vibrate?.(15);
          show(sx, sy);
        }, HOLD_MS)
      : undefined;

    const move = (ev: PointerEvent) => {
      const dist = Math.hypot(ev.clientX - sx, ev.clientY - sy);
      if (!armed) {
        if (dist > TOUCH_SLOP) finish(); // vuốt trước khi giữ đủ lâu: để trình duyệt cuộn trang
        return;
      }
      if (!started && dist < THRESHOLD) return;
      started = true;
      show(ev.clientX, ev.clientY);
    };
    // Giữ lâu trên điện thoại mở menu ngữ cảnh / chọn chữ: chặn trong lúc nhấn
    const blockMenu = (ev: Event) => ev.preventDefault();
    const finish = () => {
      window.clearTimeout(timer);
      touchDrag.current = false;
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", cancel);
      document.removeEventListener("contextmenu", blockMenu);
      setGhost(null);
      setOver("");
    };
    const up = (ev: PointerEvent) => {
      finish();
      if (!started) return;
      // Nuốt cú click sinh ra sau khi thả (không mở menu / hộp chọn)
      const swallow = (c: Event) => c.stopPropagation();
      document.addEventListener("click", swallow, { capture: true, once: true });
      setTimeout(() => document.removeEventListener("click", swallow, { capture: true }), 0);
      const { ref, inCourt } = slotAt(ev.clientX, ev.clientY);
      dropRef.current(source, ref ?? null, inCourt);
    };
    const cancel = () => finish();
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
    document.addEventListener("pointercancel", cancel);
    if (touch) document.addEventListener("contextmenu", blockMenu);
  }, []);

  const ghostEl = ghost ? (
    <span
      aria-hidden
      style={{ left: ghost.x, top: ghost.y }}
      className="pointer-events-none fixed z-50 -translate-x-1/2 -translate-y-1/2 rounded-full bg-surface px-3 py-1 text-sm font-semibold text-foreground shadow-card ring-2 ring-primary"
    >
      {ghost.label}
    </span>
  ) : null;

  return { begin, over, ghost: ghostEl };
}
