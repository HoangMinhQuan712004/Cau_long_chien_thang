import { vnMinutes } from "@/lib/format";

/**
 * Mốc 2 của T-017 (bốc cặp, bắt đầu, tỉ số, lịch sử, xếp hạng): giao diện đã dựng nhưng API chưa có ⇒ ẩn.
 * Bật `true` khi BE bàn giao mốc 2.
 */
export const MATCHES_READY = false;

/** "18h" hoặc "18h30" theo giờ Việt Nam. */
export function hourLabel(iso: string): string {
  const total = Math.round(vnMinutes(iso));
  const h = Math.floor(total / 60) % 24;
  const m = total % 60;
  return m ? `${h}h${String(m).padStart(2, "0")}` : `${h}h`;
}

/** "18h–19h". */
export const hourRange = (startIso: string, endIso: string) => `${hourLabel(startIso)}–${hourLabel(endIso)}`;

/** "YYYY-MM-DD" → "dd/mm/yyyy". */
export const dmy = (d: string) => `${d.slice(8, 10)}/${d.slice(5, 7)}/${d.slice(0, 4)}`;

/** Còn mấy chỗ: "Còn 4 chỗ" / "Đã đủ người". */
export const seatsText = (count: number, max = 8) => (count >= max ? "Đã đủ người" : `Còn ${max - count} chỗ`);
