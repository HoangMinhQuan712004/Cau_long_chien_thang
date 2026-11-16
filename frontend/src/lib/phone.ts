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

/** Hiển thị SĐT 10 số dạng "0912 345 678"; dạng khác giữ nguyên. */
export function formatPhone(phone: string): string {
  return /^0\d{9}$/.test(phone) ? `${phone.slice(0, 4)} ${phone.slice(4, 7)} ${phone.slice(7)}` : phone;
}
