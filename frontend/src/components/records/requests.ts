import "client-only";
import { looseApi } from "@/lib/api/client";
import { toApiError, type ApiError } from "@/lib/api/write";
import type { RecordVideo } from "@/lib/video";

// Video kỷ lục (T-046). TODO(T-046): đổi sang `schema.d.ts` + `api` có kiểu khi BE handoff; kiểu dưới đây là giả định theo spec.

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

/** Một số đo ở màn Admin "Kỷ lục & video". */
export type AdminSpeedRecord = {
  id: number;
  speed_kmh: number;
  measured_at: string;
  display_name: string;
  member_code: string | null;
  /** Sân (tên hoặc mã) nếu có. */
  resource_name?: string | null;
  video: RecordVideo | null;
};
export type AdminSpeedRecordList = { items: AdminSpeedRecord[]; total: number; page: number; size: number };

export const getAdminSpeedRecords = (f: { has_video?: boolean; page?: number; size?: number }) => {
  const query = Object.fromEntries(Object.entries(f).filter(([, v]) => v !== undefined));
  return read<AdminSpeedRecordList>(() => looseApi.GET(`${P}/admin/speed-records`, { params: { query } }));
};

/** Gắn / sửa video của một số đo (`write((key) => sendRecordVideo(key, id, url))`). Link sai → 422 E-REC-1. */
export const sendRecordVideo = (key: string, id: number, url: string) => looseApi.PUT(`${P}/admin/speed-records/{id}/video`, { params: { path: { id } }, body: { url }, headers: idem(key) });

export const sendRemoveRecordVideo = (key: string, id: number) => looseApi.DELETE(`${P}/admin/speed-records/{id}/video`, { params: { path: { id } }, headers: idem(key) });

/** Video ở màn hội viên "Video & kỷ lục". */
export type MemberRecordVideo = {
  speed_kmh: number;
  measured_at: string;
  /** Theo quy tắc ẩn danh T-030. */
  display_name: string;
  avatar_url: string | null;
  racket?: string | null;
  resource_name?: string | null;
  video: RecordVideo;
};
export type VideoPeriod = "week" | "month" | "year" | "all";
export const getMemberVideos = (period: VideoPeriod) => read<{ items: MemberRecordVideo[] }>(() => looseApi.GET(`${P}/member-area/record-videos`, { params: { query: { period } } }));
