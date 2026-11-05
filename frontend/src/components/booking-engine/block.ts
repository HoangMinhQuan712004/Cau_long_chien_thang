// Khối giờ của đơn đặt tại quầy (T-019, T-025): kiểu + hàm nhỏ dùng chung cho lịch và popup đặt sân.

export type Block = { resource_code: string; start_hour: number; end_hour: number };

/** Một đơn tối đa bao nhiêu khối (cùng giới hạn với backend). */
export const MAX_BLOCKS = 20;
const pad2 = (n: number) => String(n).padStart(2, "0");
export const hourText = (h: number) => `${pad2(h)}:00`;
export const blockKey = (b: Block) => `${b.resource_code}|${b.start_hour}`;
