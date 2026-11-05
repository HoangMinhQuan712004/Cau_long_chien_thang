"use client";

import { useRef, useState } from "react";
import { ArrowDownIcon, ArrowUpIcon, Svg } from "@/components/ui/icons";
import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";
import { fill } from "@/lib/format";

// Danh sách sắp thứ tự không thư viện: kéo tay nắm bằng pointer events (chuột + cảm ứng như nhau),
// bàn phím (Space nhấc, ↑/↓ di chuyển, Space/Enter thả, Esc hủy) và nút ↑ ↓; aria-live đọc vị trí mới.

export type SortItem = { key: string; label: string; icon: React.ReactNode };
type T = Dictionary["menuOrder"];
type Drag = { from: number; over: number; dy: number; startY: number; rowH: number };

const BTN = "grid size-11 shrink-0 place-items-center rounded-lg text-muted transition-colors hover:bg-primary-softer hover:text-foreground focus-ring disabled:pointer-events-none disabled:opacity-35";

/** Tay nắm ⠿ (6 chấm). */
const GripIcon = () => (
  <Svg size={18} strokeWidth={2.6}>
    <path d="M9 6h.01M15 6h.01M9 12h.01M15 12h.01M9 18h.01M15 18h.01" />
  </Svg>
);

export function SortableList({ items, onMove, t }: { items: SortItem[]; onMove: (from: number, to: number) => void; t: T }) {
  const [drag, setDrag] = useState<Drag | null>(null);
  const [lifted, setLifted] = useState<{ key: string; origin: number } | null>(null);
  const [announce, setAnnounce] = useState("");
  const rows = useRef<(HTMLLIElement | null)[]>([]);
  const total = items.length;
  const say = (tpl: string, label: string, pos: number) => setAnnounce(fill(tpl, { label, pos: pos + 1, total }));

  // Kéo bằng con trỏ: dòng đi theo tay, vạch xanh ở chỗ sẽ thả; thả ⇒ đổi chỗ
  function onPointerDown(e: React.PointerEvent<HTMLButtonElement>, i: number) {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    setDrag({ from: i, over: i, dy: 0, startY: e.clientY, rowH: rows.current[i]?.offsetHeight ?? 56 });
  }
  function onPointerMove(e: React.PointerEvent<HTMLButtonElement>) {
    if (!drag) return;
    const dy = e.clientY - drag.startY;
    const over = Math.max(0, Math.min(total - 1, drag.from + Math.round(dy / drag.rowH)));
    setDrag({ ...drag, dy, over });
  }
  function onPointerUp() {
    if (!drag) return;
    if (drag.over !== drag.from) {
      onMove(drag.from, drag.over);
      say(t.dropped, items[drag.from].label, drag.over);
    }
    setDrag(null);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLButtonElement>, i: number) {
    const item = items[i];
    if (e.key === " " || e.key === "Enter") {
      e.preventDefault();
      if (lifted) return (setLifted(null), say(t.dropped, item.label, i));
      setLifted({ key: item.key, origin: i });
      return say(t.lifted, item.label, i);
    }
    if (!lifted) return;
    if (e.key === "Escape") {
      e.preventDefault();
      onMove(i, lifted.origin);
      setLifted(null);
      return say(t.cancelled, item.label, lifted.origin);
    }
    const to = e.key === "ArrowUp" ? i - 1 : e.key === "ArrowDown" ? i + 1 : -1;
    if (to < 0 || to >= total) return;
    e.preventDefault();
    onMove(i, to); // React giữ nút DOM theo key ⇒ tay nắm vẫn đang focus ở vị trí mới
    say(t.moved, item.label, to);
  }

  return (
    <>
      <p id="sort-help" className="sr-only">{t.keyHelp}</p>
      <ul aria-label={t.listLabel} aria-describedby="sort-help" className="flex flex-col">
        {items.map((it, i) => {
          const isDragged = drag?.from === i;
          // Các dòng giữa chỗ cũ và chỗ thả dịch nhường chỗ ⇒ thấy trước thứ tự mới, dòng đích không bị che
          const shift = !drag || isDragged ? 0 : drag.from < drag.over && i > drag.from && i <= drag.over ? -drag.rowH : drag.over < drag.from && i >= drag.over && i < drag.from ? drag.rowH : 0;
          const isLifted = lifted?.key === it.key;
          // Vạch thả: phía trên dòng đích khi kéo lên, phía dưới khi kéo xuống
          const mark = drag && drag.over === i && drag.over !== drag.from ? (drag.over < drag.from ? "top-0" : "bottom-0") : null;
          return (
            <li
              key={it.key}
              ref={(el) => {
                rows.current[i] = el;
              }}
              style={isDragged ? { transform: `translateY(${drag.dy}px)` } : shift ? { transform: `translateY(${shift}px)` } : undefined}
              className={cn(
                `
                  relative flex min-h-14 items-center gap-2 border-b border-border/60 bg-surface
                  px-2
                  last:border-b-0
                  sm:px-4
                `,
                // Dòng đang kéo theo sát tay (không transition); dòng nhường chỗ trượt mượt (tắt khi giảm chuyển động)
                isDragged ? "z-10 rounded-lg shadow-card ring-1 ring-primary/40" : `
                  transition-transform duration-150
                  motion-reduce:transition-none
                `,
                isLifted && "bg-primary-softer ring-2 ring-primary/50",
              )}
            >
              {mark ? <span aria-hidden className={cn(`
                absolute inset-x-2 h-0.5 rounded-full bg-primary
              `, mark)} /> : null}
              <button
                type="button"
                aria-label={fill(t.handle, { label: it.label })}
                aria-pressed={isLifted}
                onPointerDown={(e) => onPointerDown(e, i)}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={() => setDrag(null)}
                onKeyDown={(e) => onKeyDown(e, i)}
                onBlur={() => setLifted(null)}
                className={cn(BTN, "cursor-grab touch-none active:cursor-grabbing")}
              >
                <GripIcon />
              </button>
              <span aria-hidden className="shrink-0 text-primary">{it.icon}</span>
              <span className="min-w-0 flex-1 truncate text-sm font-medium">{it.label}</span>
              <button type="button" aria-label={fill(t.moveUp, { label: it.label })} disabled={i === 0} onClick={() => (onMove(i, i - 1), say(t.moved, it.label, i - 1))} className={BTN}>
                <ArrowUpIcon size={18} />
              </button>
              <button type="button" aria-label={fill(t.moveDown, { label: it.label })} disabled={i === total - 1} onClick={() => (onMove(i, i + 1), say(t.moved, it.label, i + 1))} className={BTN}>
                <ArrowDownIcon size={18} />
              </button>
            </li>
          );
        })}
      </ul>
      <p aria-live="polite" className="sr-only">{announce}</p>
    </>
  );
}
