"use client";

import { useEffect, useRef } from "react";

/** Gọi `fn` mỗi `ms` khi tab đang hiện; quay lại tab thì gọi ngay; tab ẩn thì dừng (T-017 AC21). */
export function usePolling(fn: () => void, ms: number) {
  const ref = useRef(fn);
  useEffect(() => {
    ref.current = fn;
  });
  useEffect(() => {
    let id: ReturnType<typeof setInterval> | null = null;
    const tick = () => ref.current();
    const start = () => {
      if (id === null) id = setInterval(tick, ms);
    };
    const stop = () => {
      if (id !== null) clearInterval(id);
      id = null;
    };
    const onVis = () => {
      if (document.visibilityState === "visible") {
        tick();
        start();
      } else stop();
    };
    if (document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", onVis);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [ms]);
}
