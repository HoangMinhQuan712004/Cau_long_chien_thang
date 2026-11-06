import "client-only";
import { api } from "@/lib/api/client";
import { type ApiError, toApiError, type WriteResult, write } from "@/lib/api/write";
import type { Crop, MeInput, MemberMe } from "./types";

// Lời gọi API khu hội viên (chỉ khách có hồ sơ hội viên). Mọi API lấy hồ sơ theo phiên, không theo tham số.

export type Read<T> = { ok: true; data: T } | { ok: false; error: ApiError };

export async function getMe(): Promise<Read<MemberMe>> {
  try {
    const { data, error, response } = await api.GET("/api/v1/member-area/me");
    if (response.ok && data !== undefined) return { ok: true, data };
    return { ok: false, error: toApiError(error, response.status) };
  } catch {
    return { ok: false, error: { status: 0, code: "E-017", message: "Mất kết nối. Vui lòng thử lại.", extra: {} } };
  }
}

export function putMe(body: MeInput): Promise<WriteResult<MemberMe>> {
  return write((key) => api.PUT("/api/v1/member-area/me", { body, headers: { "Idempotency-Key": key } }));
}

/** Body multipart ảnh đại diện (dùng chung cho API hội viên và quản trị). */
export function avatarBody(file: Blob, crop: Crop) {
  const form = new FormData();
  form.set("file", file, (file as File).name || "avatar");
  form.set("crop_x", String(Math.round(crop.x)));
  form.set("crop_y", String(Math.round(crop.y)));
  form.set("crop_size", String(Math.round(crop.size)));
  return {
    // Gửi nguyên FormData (trình duyệt tự đặt boundary)
    body: form as unknown as { file: string; crop_x: number; crop_y: number; crop_size: number },
    bodySerializer: (b: unknown) => b as FormData,
  };
}

export function putAvatar(file: Blob, crop: Crop): Promise<WriteResult<{ avatar_url: string }>> {
  return write((key) => api.PUT("/api/v1/member-area/me/avatar", { ...avatarBody(file, crop), headers: { "Idempotency-Key": key } }));
}

export function deleteAvatar(): Promise<WriteResult<unknown>> {
  return write((key) => api.DELETE("/api/v1/member-area/me/avatar", { headers: { "Idempotency-Key": key } }));
}
