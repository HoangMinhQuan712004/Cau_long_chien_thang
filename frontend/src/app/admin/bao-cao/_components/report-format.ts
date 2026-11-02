// Cách viết số của màn Báo cáo (BR-010): tiền "99.850.000 đ", triệu "17,0" / "<0,1", phần trăm "83,3%"

const ONE_DECIMAL = new Intl.NumberFormat("vi-VN", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const INTEGER = new Intl.NumberFormat("vi-VN");

/** Tiền đầy đủ: "99.850.000 đ" (không dùng ₫). */
export const money = (n: number) => `${INTEGER.format(n)} đ`;

/** Số nguyên có chấm ngăn nghìn: "1.234". */
export const count = (n: number) => INTEGER.format(n);

/** Làm tròn 1 chữ số, nửa lên (tiền là số nguyên VND nên n/100.000 không lệch dấu phẩy động ở .5). */
export const round1 = (x: number) => Math.round(x * 10) / 10;

/** Tiền ra triệu, 1 chữ số: 16.950.000 ⇒ "17,0"; > 0 mà tròn ra 0 ⇒ "<0,1". */
export function millions(n: number) {
  const m = Math.round(n / 100_000) / 10;
  return n > 0 && m === 0 ? `<${ONE_DECIMAL.format(0.1)}` : ONE_DECIMAL.format(m);
}

/** Số 1 chữ số thập phân dấu phẩy: 2,5. */
export const decimal1 = (x: number) => ONE_DECIMAL.format(round1(x));

/** Số giờ sân (có thể lẻ): 5 ⇒ "5", 2,5 ⇒ "2,5". */
export const hoursCount = (x: number) => (Number.isInteger(round1(x)) ? INTEGER.format(round1(x)) : decimal1(x));

/** Thứ viết tắt theo chỉ số 0 = T2 … 6 = CN (heatmap). */
export const WEEKDAY_SHORT = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"] as const;

/** Chỉ số thứ 0 = T2 … 6 = CN của ngày YYYY-MM-DD. */
export const weekdayIndex = (isoDate: string) => (new Date(`${isoDate}T00:00:00Z`).getUTCDay() + 6) % 7;

export const isWeekend = (isoDate: string) => weekdayIndex(isoDate) >= 5;

/** Điền biến vào câu mẫu: fill("Tổng {n} sân", { n: 6 }). */
export const fill = (text: string, vars: Record<string, string | number>) =>
  text.replace(/\{(\w+)\}/g, (all, key: string) => (key in vars ? String(vars[key]) : all));
