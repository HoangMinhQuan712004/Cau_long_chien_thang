import "client-only";
import { looseApi } from "@/lib/api/client";
import { toApiError, type ApiError } from "@/lib/api/write";
import type { components } from "@/lib/api/schema";

// Video kỷ lục (T-046): kiểu sinh từ schema.d.ts.

export type Read<T> = { ok: true; data: T } | { ok: false; error: ApiError };

async function read<T>(call: () => Promise<{ data?: unknown; error?: unknown; response: Response }>): Promise<Read<T>> {
  try {
    const { data, error, response } = await call();
    if (response.ok && data !== undefined) return { ok: true, data: data as T };
    return { ok: false, error: toApiError(error, response.status) };
  } catch {
    return { ok: false, error: { status: 0, code: "E-017", message: "Mất kết nối. Vui lòng thử lại.", extra: {} } };
  }
}

const P = "/api/v1";
const idem = (key: string) => ({ "Idempotency-Key": key });

export type AdminSpeedRecord = components["schemas"]["AdminSpeedRecordRow"];
export type AdminSpeedRecordList = components["schemas"]["AdminSpeedRecordList"];

export const getAdminSpeedRecords = (f: { has_video?: boolean; page?: number; size?: number }) => {
  const query = Object.fromEntries(Object.entries(f).filter(([, v]) => v !== undefined));
  return read<AdminSpeedRecordList>(() => looseApi.GET(`${P}/admin/speed-records`, { params: { query } }));
};

/** Gắn / sửa video của một số đo (`write((key) => sendRecordVideo(key, id, url))`). Link sai → 422 E-REC-1. */
export const sendRecordVideo = (key: string, id: number, url: string) => looseApi.PUT(`${P}/admin/speed-records/{record_id}/video`, { params: { path: { record_id: id } }, body: { url }, headers: idem(key) });

export const sendRemoveRecordVideo = (key: string, id: number) => looseApi.DELETE(`${P}/admin/speed-records/{record_id}/video`, { params: { path: { record_id: id } }, headers: idem(key) });

/** Video ở màn hội viên "Video & kỷ lục": chỉ số đo có video, tối đa 60; tên theo quy tắc ẩn danh T-030. */
export type MemberRecordVideo = components["schemas"]["RecordVideoCard"];
export type VideoPeriod = "week" | "month" | "year" | "all";
export const getMemberVideos = (period: VideoPeriod) => read<components["schemas"]["RecordVideoList"]>(() => looseApi.GET(`${P}/member-area/record-videos`, { params: { query: { period } } }));
