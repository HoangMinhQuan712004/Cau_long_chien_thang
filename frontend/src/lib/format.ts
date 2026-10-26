const TZ = "Asia/Ho_Chi_Minh";

export const formatVnd = (n: number) =>
  new Intl.NumberFormat("vi-VN", { style: "currency", currency: "VND" }).format(n);

export const formatTime = (iso: string) =>
  new Intl.DateTimeFormat("vi-VN", { hour: "2-digit", minute: "2-digit", timeZone: TZ }).format(
    new Date(iso),
  );

export const formatDate = (iso: string) =>
  new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium", timeZone: TZ }).format(new Date(iso));

/** Ngày hiện tại theo giờ Việt Nam, dạng YYYY-MM-DD. */
export const todayVn = () => new Intl.DateTimeFormat("en-CA", { timeZone: TZ }).format(new Date());

/** Ghép ngày (YYYY-MM-DD) + giờ (HH:mm) theo giờ Việt Nam (UTC+7, không DST) thành ISO. */
export const vnIso = (date: string, time: string) => `${date}T${time}:00+07:00`;

export const DAY_NAMES = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"];

export const BOOKING_STATUS_LABEL: Record<string, string> = {
  pending: "Chờ thanh toán",
  confirmed: "Đã xác nhận",
  completed: "Hoàn thành",
  cancelled: "Đã hủy",
  expired: "Hết hạn giữ chỗ",
};

/** Số có dấu chấm ngăn cách hàng nghìn (không kèm ký hiệu tiền), vd 150.000. */
export const formatNumber = (n: number) => new Intl.NumberFormat("vi-VN").format(n);

/** "2026-02-16" -> "16/02". Cắt chuỗi, không qua Date nên không lệch múi giờ. */
export const formatDayMonth = (isoDate: string) => `${isoDate.slice(8, 10)}/${isoDate.slice(5, 7)}`;

/** "2026-02-16" -> "16/02/2026". */
export const formatDayMonthYear = (isoDate: string) => `${formatDayMonth(isoDate)}/${isoDate.slice(0, 4)}`;

const VN_OFFSET_MS = 7 * 3600_000;

/** Số phút trong ngày (giờ Việt Nam) của một mốc ISO. */
export const vnMinutes = (iso: string) => {
  const d = new Date(new Date(iso).getTime() + VN_OFFSET_MS);
  return d.getUTCHours() * 60 + d.getUTCMinutes() + d.getUTCSeconds() / 60;
};

/** Ngày (YYYY-MM-DD, giờ Việt Nam) của một mốc ISO. */
export const vnDate = (iso: string) => new Date(new Date(iso).getTime() + VN_OFFSET_MS).toISOString().slice(0, 10);

/** Cộng/trừ ngày cho chuỗi YYYY-MM-DD (không qua múi giờ). */
export const addDaysIso = (isoDate: string, n: number) => {
  const d = new Date(`${isoDate}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

const WEEKDAY = ["Chủ nhật", "Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7"];

/** "2026-10-26" -> "Thứ 2, 26/10/2026". */
export const formatLongDate = (isoDate: string) =>
  `${WEEKDAY[new Date(`${isoDate}T00:00:00Z`).getUTCDay()]}, ${formatDayMonthYear(isoDate)}`;

/** "HH:MM" -> "HH:MM" bỏ giây nếu có. */
export const hhmm = (t: string) => t.slice(0, 5);

/** Ngày + giờ theo giờ Việt Nam: "26/10/2026 18:04". */
export const formatDateTime = (iso: string) => `${formatDayMonthYear(vnDate(iso))} ${formatTime(iso)}`;
