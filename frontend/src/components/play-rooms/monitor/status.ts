import type { MonitorMatch, MonitorRoomStatus } from "./types";

export const STATUS_LABEL: Record<MonitorRoomStatus, string> = {
  upcoming: "Sắp tới",
  playing: "Đang chơi",
  ended: "Đã kết thúc",
  cancelled: "Booking đã hủy",
};

export const STATUS_VARIANT: Record<MonitorRoomStatus, "info" | "success" | "neutral" | "danger"> = {
  upcoming: "info",
  playing: "success",
  ended: "neutral",
  cancelled: "danger",
};

/** Trạng thái hàng chờ của thành viên trong phòng. */
export const QUEUE_LABEL: Record<string, string> = { waiting: "Đang chờ", queued: "Đang chờ", playing: "Đang đánh", resting: "Đang nghỉ" };

/** Trận chưa có kết quả (đã bốc cặp hoặc đang đánh). */
export const isLive = (m: MonitorMatch) => m.status === "playing" || m.status === "drawn";
