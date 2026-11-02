"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { SlotRef } from "./lineup";

// Kéo thả bằng pointer events (chuột / bút). Cảm ứng không kéo: dùng bấm ô → chọn người (T-027 AC3).

export type DragSource = { kind: "member"; id: number } | { kind: "slot"; ref: SlotRef };
/** `null` = thả ngoài sân. */
export type DropTarget = SlotRef | null;

const THRESHOLD = 6;

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

  const begin = useCallback((e: React.PointerEvent, source: DragSource, label: string) => {
    if (e.pointerType === "touch" || e.button !== 0) return;
    const sx = e.clientX;
    const sy = e.clientY;
    let started = false;

    const move = (ev: PointerEvent) => {
      if (!started && Math.hypot(ev.clientX - sx, ev.clientY - sy) < THRESHOLD) return;
      started = true;
      setGhost({ label, x: ev.clientX, y: ev.clientY });
      const { ref } = slotAt(ev.clientX, ev.clientY);
      setOver(ref ? `${ref.team}-${ref.idx}` : "");
    };
    const finish = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", cancel);
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
