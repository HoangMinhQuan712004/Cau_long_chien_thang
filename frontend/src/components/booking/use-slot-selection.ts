import { useMemo, useState } from "react";
import type { components } from "@/lib/api/schema";
import { vnIso } from "@/lib/format";

export type Availability = components["schemas"]["AvailabilityOut"];
type SlotIn = components["schemas"]["SlotIn"];

const toMinutes = (t: string) => {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
};

// Phút trong ngày ⇒ "HH:mm"
export const toHHmm = (min: number) =>
  `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;

// Gộp các ô liền nhau trên cùng một sân thành 1 slot
function groupSelection(date: string, selected: Set<string>, step: number): SlotIn[] {
  const byCourt = new Map<number, number[]>();
  for (const key of selected) {
    const [court, start] = key.split("|").map(Number);
    byCourt.set(court, [...(byCourt.get(court) ?? []), start]);
  }
  const slots: SlotIn[] = [];
  for (const [court_id, starts] of byCourt) {
    starts.sort((a, b) => a - b);
    let from = starts[0];
    let prev = starts[0];
    for (const s of [...starts.slice(1), Infinity]) {
      if (s !== prev + step) {
        slots.push({ court_id, start: vnIso(date, toHHmm(from)), end: vnIso(date, toHHmm(prev + step)) });
        from = s;
      }
      prev = s;
    }
  }
  return slots;
}

// Ô đang chọn trên lưới giờ của một ngày: hàng giờ, ô kín/quá giờ, các slot đã gộp để báo giá/đặt
export function useSlotSelection(date: string, board: { data: Availability; loadedAt: number } | null) {
  const data = board?.data ?? null;
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const step = data?.slot_minutes ?? 30;

  const rows = useMemo(() => {
    if (!data) return [];
    const out: number[] = [];
    const close = toMinutes(data.close_time) || 24 * 60;
    for (let m = toMinutes(data.open_time); m < close; m += step) out.push(m);
    return out;
  }, [data, step]);

  const slots = useMemo(() => groupSelection(date, selected, step), [date, selected, step]);

  // Ô đã kín, hoặc đã qua giờ tính từ lúc tải lịch
  const isBusy = (courtId: number, minute: number) => {
    const start = Date.parse(vnIso(date, toHHmm(minute)));
    const end = start + step * 60_000;
    if (!board || start <= board.loadedAt) return true;
    const court = data?.courts.find((c) => c.court_id === courtId);
    return !!court?.busy.some((b) => Date.parse(b.start) < end && Date.parse(b.end) > start);
  };

  const toggle = (key: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return { rows, slots, selected, isBusy, toggle, clear: () => setSelected(new Set()) };
}
