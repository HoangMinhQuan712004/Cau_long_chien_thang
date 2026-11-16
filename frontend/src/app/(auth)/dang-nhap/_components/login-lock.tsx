import { useState } from "react";
import { Alert } from "@/components/ui/alert";
import { useCountdown } from "@/hooks/use-countdown";
import { formatCountdown } from "@/lib/format";

type Lock = { until: number; minutes: number; template: string };

// Tạm khóa E-002/E-008: đếm ngược tới `until`, hết giờ thì gọi `onEnd`
export function useLoginLock(onEnd: () => void) {
  const [lock, setLock] = useState<Lock | null>(null);
  const remaining = useCountdown(lock?.until ?? null, () => {
    setLock(null);
    onEnd();
  });
  const start = (retryAfter: number, template: string) =>
    setLock({ until: Date.now() + retryAfter * 1000, minutes: Math.ceil(retryAfter / 60), template });
  return { lock, remaining, start };
}

// Câu khóa có đồng hồ; trình đọc màn hình chỉ nghe số phút (không đọc lại mỗi giây)
export function LockedAlert({ lock, seconds, minutesText }: { lock: Lock; seconds: number; minutesText: string }) {
  const [before, after] = lock.template.split("{time}");
  return (
    <Alert variant="error">
      <span aria-hidden>
        {before}
        <span className="font-semibold tabular-nums">{formatCountdown(seconds)}</span>
        {after}
      </span>
      <span className="sr-only">
        {lock.template.replace("{time}", minutesText.replace("{n}", String(lock.minutes)))}
      </span>
    </Alert>
  );
}
