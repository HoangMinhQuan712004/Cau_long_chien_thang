import type { Cell, WebCalendar } from "./types";

// Hàm thuần của luồng đặt sân: khóa ô, gom ô đã chọn theo sân.

export const cellKey = (c: Cell) => `${c.code}|${c.hour}`;
export const pad2 = (n: number) => String(n).padStart(2, "0");
const range = (a: number, b: number) => `${pad2(a)}:00 – ${pad2(b)}:00`;

export type Group = { code: string; name: string; hours: number[]; ranges: string; amount: number };

/** Gom ô đã chọn theo sân (đúng thứ tự sân trên lưới), nối giờ liền nhau: "17:00 – 18:00, 19:00 – 21:00". */
export function summarize(calendar: WebCalendar, cells: Cell[], price: Map<string, number>): Group[] {
  const out: Group[] = [];
  for (const r of calendar.resources) {
    const hours = cells.filter((c) => c.code === r.code).map((c) => c.hour).sort((a, b) => a - b);
    if (!hours.length) continue;
    const parts: string[] = [];
    let start = hours[0];
    let prev = hours[0];
    for (const h of hours.slice(1)) {
      if (h === prev + 1) {
        prev = h;
        continue;
      }
      parts.push(range(start, prev + 1));
      start = prev = h;
    }
    parts.push(range(start, prev + 1));
    out.push({
      code: r.code,
      name: r.name,
      hours,
      ranges: parts.join(", "),
      amount: hours.reduce((s, h) => s + (price.get(`${r.code}|${h}`) ?? 0), 0),
    });
  }
  return out;
}
