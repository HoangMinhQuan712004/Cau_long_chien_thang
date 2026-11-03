import { vnMinutes } from "@/lib/format";

/**
 * Mốc 2 của T-017 (bốc cặp, bắt đầu, tỉ số, lịch sử, xếp hạng): BE đã bàn giao (f166cf5).
 * Cờ giữ lại để tắt nhanh nếu cần.
 */
export const MATCHES_READY = true;

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

/** "Hạng Khá – Bán chuyên" · "Hạng từ Khá" · "Hạng đến Trung bình"; không giới hạn ⇒ null (T-031). */
export function tierRangeText(r: { min: string | null; max: string | null } | null | undefined): string | null {
  if (!r || (!r.min && !r.max)) return null;
  if (r.min && r.max) return r.min === r.max ? `Hạng ${r.min}` : `Hạng ${r.min} – ${r.max}`;
  return r.min ? `Hạng từ ${r.min}` : `Hạng đến ${r.max}`;
}

/** Lý do ngắn khi nút "Xin vào" mờ vì hạng (T-031 AC5). */
export const joinBlockText = (b: "out_of_range" | "unranked" | null | undefined): string | null =>
  b === "out_of_range" ? "Hạng của bạn ngoài khoảng của phòng" : b === "unranked" ? "Bạn chưa được xếp hạng. Liên hệ quầy để được xếp hạng." : null;

/** Còn mấy chỗ: "Còn 4 chỗ" / "Đã đủ người". */
export const seatsText = (count: number, max = 8) => (count >= max ? "Đã đủ người" : `Còn ${max - count} chỗ`);
