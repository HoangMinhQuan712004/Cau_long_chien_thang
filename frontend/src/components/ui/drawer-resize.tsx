"use client";

import { useRef, useState } from "react";
import { cn } from "@/lib/cn";

const DEFAULT_WIDTH = 520; // Figma P5c
const MIN_WIDTH = 420;
const MAX_RATIO = 0.9; // tối đa 90vw
const KEY_STEP = 32;

// Giới hạn theo khung nhìn hiện tại
function clamp(width: number): number {
  const max = Math.max(MIN_WIDTH, Math.round(window.innerWidth * MAX_RATIO));
  return Math.min(max, Math.max(MIN_WIDTH, Math.round(width)));
}

// localStorage có thể bị chặn (trình duyệt riêng tư, webview) ⇒ bỏ qua, dùng mặc định
function load(key: string | undefined): number {
  if (!key || typeof window === "undefined") return DEFAULT_WIDTH;
  try {
    const saved = Number(window.localStorage.getItem(key));
    return saved ? clamp(saved) : DEFAULT_WIDTH;
  } catch {
    return DEFAULT_WIDTH;
  }
}

function save(key: string | undefined, width: number) {
  if (!key) return;
  try {
    window.localStorage.setItem(key, String(width));
  } catch {
    // Không lưu được ⇒ lần sau về mặc định
  }
}

/** Bề rộng ngăn kéo phải kéo dãn được (máy tính); nhớ theo `storageKey`. */
export function useDrawerWidth(storageKey?: string) {
  const [width, setWidth] = useState(() => load(storageKey));
  const set = (next: number, persist = true) => {
    const value = clamp(next);
    setWidth(value);
    if (persist) save(storageKey, value);
  };
  return { width, set, reset: () => set(DEFAULT_WIDTH) };
}

type HandleProps = {
  width: number;
  onChange: (width: number, persist?: boolean) => void;
  onReset: () => void;
  label: string;
};

/** Thanh kéo ở cạnh trái ngăn kéo phải: kéo chuột / chạm, phím ←/→ (32px), bấm đúp về mặc định. Chỉ hiện từ lg. */
export function DrawerResizeHandle({ width, onChange, onReset, label }: HandleProps) {
  const dragging = useRef(false);

  // Ngăn kéo neo cạnh phải ⇒ rộng = mép phải màn hình − vị trí con trỏ
  const widthAt = (clientX: number) => window.innerWidth - clientX;

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={width}
      aria-valuemin={MIN_WIDTH}
      aria-valuemax={typeof window === "undefined" ? undefined : Math.round(window.innerWidth * MAX_RATIO)}
      tabIndex={0}
      onPointerDown={(e) => {
        dragging.current = true;
        e.currentTarget.setPointerCapture(e.pointerId);
        document.body.style.userSelect = "none"; // không bôi đen chữ khi kéo
      }}
      onPointerMove={(e) => {
        if (dragging.current) onChange(widthAt(e.clientX), false);
      }}
      onPointerUp={(e) => {
        if (!dragging.current) return;
        dragging.current = false;
        document.body.style.userSelect = "";
        onChange(widthAt(e.clientX)); // thả tay mới lưu
      }}
      onPointerCancel={() => {
        dragging.current = false;
        document.body.style.userSelect = "";
      }}
      onDoubleClick={onReset}
      onKeyDown={(e) => {
        // Thanh ở cạnh trái: ← kéo rộng ra, → thu hẹp lại
        if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
          e.preventDefault();
          onChange(width + (e.key === "ArrowLeft" ? KEY_STEP : -KEY_STEP));
        }
      }}
      className={cn(`
        group absolute inset-y-0 left-0 z-10 hidden w-3 -translate-x-1/2 cursor-col-resize
        touch-none outline-none
        lg:block
      `)}
    >
      <span
        aria-hidden
        className={cn(`
          absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 bg-transparent transition-colors
          group-hover:bg-primary/40
          group-focus-visible:bg-primary
        `)}
      />
    </div>
  );
}
