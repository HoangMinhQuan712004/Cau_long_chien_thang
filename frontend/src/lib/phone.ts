/** Chuẩn hóa SĐT: bỏ khoảng trắng / chấm / gạch, "+84…" → "0…". */
export function normalizePhone(raw: string): string {
  const compact = raw.replace(/[\s.-]/g, "");
  if (compact.startsWith("+84")) return `0${compact.slice(3).replace(/\D/g, "")}`;
  const digits = compact.replace(/\D/g, "");
  if (digits.startsWith("84") && digits.length === 11) return `0${digits.slice(2)}`;
  return digits;
}

/** SĐT hợp lệ: "0" + 9 chữ số (đã chuẩn hóa). */
export const isValidPhone = (normalized: string) => /^0\d{9}$/.test(normalized);
