import type { MonitorMatch, MonitorMember, MonitorRoomStatus } from "./types";

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
export const QUEUE_LABEL: Record<MonitorMember["queue_state"], string> = { waiting: "Đang chờ", playing: "Đang đánh" };

/** Trận chưa có kết quả (đã bốc cặp hoặc đang đánh). */
export const isLive = (m: MonitorMatch) => m.status !== "finished";
