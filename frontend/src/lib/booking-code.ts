/**
 * Chuẩn hóa mã nhập tay về dạng chuẩn: `BK-YYYYMMDD-NNN` (mã đơn/sự kiện), `…-NN` (mã khối), `…-Vnn` (vé).
 * Nhận cả mã viết liền / thường / có khoảng trắng ("bk2026103000301" → "BK-20261030-003-01"), giống tra cứu của khách.
 * Không khớp dạng nào thì trả mã đã bỏ khoảng trắng, viết hoa, để backend báo không tìm thấy.
 */
export function normalizeBookingCode(raw: string): string {
  const compact = raw.replace(/[\s-]+/g, "").toUpperCase();
  const m = /^BK(\d{8})(\d{3})(?:(\d{2})|(V\d{2}))?$/.exec(compact);
  if (!m) return raw.replace(/\s+/g, "").toUpperCase();
  const suffix = m[3] ?? m[4];
  return `BK-${m[1]}-${m[2]}${suffix ? `-${suffix}` : ""}`;
}
