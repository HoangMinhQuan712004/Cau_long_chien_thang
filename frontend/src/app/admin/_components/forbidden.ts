// Tách khỏi forbidden-toast.tsx ("use client"): server import hằng từ file client sẽ nhận tham chiếu, không phải giá trị

/** Tham số gắn khi chuyển về vì không đủ quyền (vd Nhân viên mở link Lịch sử thao tác). */
export const FORBIDDEN_KEY = "ly-do";
export const FORBIDDEN_VALUE = "khong-quyen";
export const FORBIDDEN_PARAM = `${FORBIDDEN_KEY}=${FORBIDDEN_VALUE}`;
