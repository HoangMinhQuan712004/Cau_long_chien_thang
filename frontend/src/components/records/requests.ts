import "client-only";
import { api, looseApi } from "@/lib/api/client";
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

/** `from` / `to`: khoảng ngày đo YYYY-MM-DD theo giờ sân, gồm cả hai đầu (Admin, 21/11). */
export const getAdminSpeedRecords = (f: { has_video?: boolean; status?: RecordStatus; source?: RecordSource; page?: number; size?: number; from?: string; to?: string }) => {
  const query = Object.fromEntries(Object.entries(f).filter(([, v]) => v !== undefined));
  return read<AdminSpeedRecordList>(() => looseApi.GET(`${P}/admin/speed-records`, { params: { query } }));
};

export const sendRemoveRecordVideo = (key: string, id: number) => looseApi.DELETE(`${P}/admin/speed-records/{record_id}/video`, { params: { path: { record_id: id } }, headers: idem(key) });

/** Video ở màn hội viên "Video & kỷ lục": chỉ số đo có video, tối đa 60; tên theo quy tắc ẩn danh T-030. */
export type MemberRecordVideo = components["schemas"]["RecordVideoCard"];

// ---- T-048: dòng thời gian phá kỷ lục (kiểu sinh từ schema.d.ts). Không có tham số `date`: kỳ luôn là kỳ chứa hôm nay ----
export type RecordBreakItem = components["schemas"]["RecordBreakItem"];
export type RecordBreakList = components["schemas"]["RecordBreakList"];
export const getRecordBreaks = (period: VideoPeriod) => read<RecordBreakList>(() => looseApi.GET(`${P}/member-area/record-breaks`, { params: { query: { period } } }));
export type VideoPeriod = "week" | "month" | "year" | "all";
export const getMemberVideos = (period: VideoPeriod) => read<components["schemas"]["RecordVideoList"]>(() => looseApi.GET(`${P}/member-area/record-videos`, { params: { query: { period } } }));

// ---- T-047: duyệt / xóa số đo (Admin). 25/11: bỏ nhập tay – số đo chỉ đến từ camera AI ----
export type AdminRecordRow = AdminSpeedRecord;
export type RecordSource = AdminRecordRow["source"];
export type RecordStatus = AdminRecordRow["status"];

export const sendAdminDeleteRecord = (key: string, id: number) => api.DELETE(`${P}/admin/speed-records/{record_id}`, { params: { path: { record_id: id } }, headers: idem(key) });

export const sendApproveRecord = (key: string, id: number) => api.POST(`${P}/admin/speed-records/{record_id}/approve`, { params: { path: { record_id: id } }, headers: idem(key) });

export const sendRejectRecord = (key: string, id: number, reason: string) => api.POST(`${P}/admin/speed-records/{record_id}/reject`, { params: { path: { record_id: id } }, body: { reason }, headers: idem(key) });

export const SOURCE_LABEL: Record<RecordSource, string> = { device: "Máy đo", admin: "Admin nhập", member: "Hội viên gửi" };
