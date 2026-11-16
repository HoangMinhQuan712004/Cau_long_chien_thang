import { useEffect, useEffectEvent, useState } from "react";

// Số giây còn lại tới mốc `until` (null ⇒ 0); về 0 thì gọi `onEnd` một lần
export function useCountdown(until: number | null, onEnd: () => void): number {
  const [now, setNow] = useState(() => Date.now());
  const handleEnd = useEffectEvent(onEnd);

  useEffect(() => {
    if (until === null) return;
    const tick = () => {
      const current = Date.now();
      setNow(current);
      if (current >= until) {
        clearInterval(timer);
        handleEnd();
      }
    };
    // Lần đầu chạy ngay (không đợi 250ms) để không hiện số giây cũ
    const first = setTimeout(tick, 0);
    const timer = setInterval(tick, 250);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [until]);

  return until === null ? 0 : Math.max(0, Math.ceil((until - now) / 1000));
}
