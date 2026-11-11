import "client-only";
import { api } from "@/lib/api/client";
import { toApiError } from "@/lib/api/write";
import type { Read } from "@/components/member-area/requests";
import type { MonitorDay, MonitorRoomDetail } from "./types";

// Theo dõi sân (T-069): chỉ đọc. Trình duyệt tự gửi If-None-Match nên ETag / 304 của API không cần xử lý riêng.

async function read<T>(call: () => Promise<{ data?: unknown; error?: unknown; response: Response }>): Promise<Read<T>> {
  try {
    const { data, error, response } = await call();
    if (response.ok && data !== undefined) return { ok: true, data: data as T };
    return { ok: false, error: toApiError(error, response.status) };
  } catch {
    return { ok: false, error: { status: 0, code: "E-017", message: "Mất kết nối. Vui lòng thử lại.", extra: {} } };
  }
}

export const getMonitorDay = (date: string) => read<MonitorDay>(() => api.GET("/api/v1/play-rooms/admin/day", { params: { query: { date } } }));
export const getMonitorRoom = (id: number) => read<MonitorRoomDetail>(() => api.GET("/api/v1/play-rooms/admin/rooms/{room_id}", { params: { path: { room_id: id } } }));
