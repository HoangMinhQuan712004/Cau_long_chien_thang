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

export const getAdminSpeedRecords = (f: { has_video?: boolean; status?: RecordStatus; source?: RecordSource; page?: number; size?: number }) => {
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

// ---- T-047: số đo nhập tay (Admin) + hội viên gửi chờ duyệt (kiểu sinh từ schema.d.ts) ----
export type AdminRecordRow = AdminSpeedRecord;
export type RecordSource = AdminRecordRow["source"];
export type RecordStatus = AdminRecordRow["status"];

/** Danh sách sân của Admin (cùng nguồn với Sân & bảng giá): gồm cả sân ngừng hoạt động. */
export type CourtOption = { code: string; name: string; is_active: boolean };
export const getAdminCourts = () =>
  read<CourtOption[]>(async () => {
    const res = await api.GET("/api/v1/booking/resources");
    return { ...res, data: res.data?.items.map((r) => ({ code: r.code, name: r.name, is_active: r.is_active })) };
  });

/** Dữ liệu một số đo gửi lên (Admin thêm / sửa, hội viên gửi). `measured_at` là ISO có múi giờ +07:00. */
export type RecordInput = { speed_kmh: number; measured_at: string; resource_code?: string | null; video_url?: string | null };

export const sendAdminCreateRecord = (key: string, body: components["schemas"]["SpeedRecordCreateIn"]) => api.POST(`${P}/admin/speed-records`, { body, headers: idem(key) });

/** Sửa: kèm `version` của dòng đang xem (E-REC-3 nếu đã bị sửa nơi khác). Chỉ ô có gửi mới đổi; null = bỏ sân / gỡ video. */
export const sendAdminUpdateRecord = (key: string, id: number, body: components["schemas"]["SpeedRecordPatchIn"]) =>
  api.PATCH(`${P}/admin/speed-records/{record_id}`, { params: { path: { record_id: id } }, body, headers: idem(key) });

export const sendAdminDeleteRecord = (key: string, id: number) => api.DELETE(`${P}/admin/speed-records/{record_id}`, { params: { path: { record_id: id } }, headers: idem(key) });

export const sendApproveRecord = (key: string, id: number) => api.POST(`${P}/admin/speed-records/{record_id}/approve`, { params: { path: { record_id: id } }, headers: idem(key) });

export const sendRejectRecord = (key: string, id: number, reason: string) => api.POST(`${P}/admin/speed-records/{record_id}/reject`, { params: { path: { record_id: id } }, body: { reason }, headers: idem(key) });

export const sendMemberSubmitRecord = (key: string, body: RecordInput & { speed_kmh: number }) => api.POST(`${P}/member-area/speed-records`, { body, headers: idem(key) });

export const sendMemberWithdrawRecord = (key: string, id: number) => api.DELETE(`${P}/member-area/speed-records/{record_id}`, { params: { path: { record_id: id } }, headers: idem(key) });

/** Số đo của chính mình (mọi trạng thái, tối đa 50, mới gửi trước) + sân chọn được + số lượt gửi tối đa mỗi ngày. */
export type MineRecord = components["schemas"]["MySpeedRecord"];
export type MineRecords = components["schemas"]["MySpeedRecordList"];
export const getMineRecords = () => read<MineRecords>(() => api.GET(`${P}/member-area/speed-records/mine`));

export const SOURCE_LABEL: Record<RecordSource, string> = { device: "Máy đo", admin: "Admin nhập", member: "Hội viên gửi" };
