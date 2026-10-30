import "client-only";
import { looseApi } from "@/lib/api/client";
import { type ApiError, toApiError, type WriteResult, write } from "@/lib/api/write";
import type { Crop, MeInput, MemberMe } from "./types";

// Lời gọi API khu hội viên (chỉ khách đã liên kết hồ sơ). Mọi API lấy hồ sơ theo phiên.
// NEXT_PUBLIC_MEMBER_AREA_MOCK=1: dữ liệu giả trong bộ nhớ (dựng giao diện khi API chưa có).

export type Read<T> = { ok: true; data: T } | { ok: false; error: ApiError };

const P = "/api/v1/member-area";
const MOCK = process.env.NEXT_PUBLIC_MEMBER_AREA_MOCK === "1";
const mock = () => import("./mock");

export async function getMe(): Promise<Read<MemberMe>> {
  if (MOCK) return (await mock()).getMe();
  try {
    const { data, error, response } = await looseApi.GET(`${P}/me`, {});
    if (response.ok && data !== undefined) return { ok: true, data: data as MemberMe };
    return { ok: false, error: toApiError(error, response.status) };
  } catch {
    return { ok: false, error: { status: 0, code: "E-017", message: "Mất kết nối. Vui lòng thử lại.", extra: {} } };
  }
}

export async function putMe(body: MeInput): Promise<WriteResult<MemberMe>> {
  if (MOCK) return (await mock()).putMe(body);
  return write((key) => looseApi.PUT(`${P}/me`, { body, headers: { "Idempotency-Key": key } }));
}

export async function putAvatar(file: Blob, crop: Crop): Promise<WriteResult<{ avatar_url: string }>> {
  if (MOCK) return (await mock()).putAvatar(file);
  const form = new FormData();
  form.set("file", file, (file as File).name || "avatar");
  form.set("crop_x", String(Math.round(crop.x)));
  form.set("crop_y", String(Math.round(crop.y)));
  form.set("crop_size", String(Math.round(crop.size)));
  return write((key) =>
    looseApi.PUT(`${P}/me/avatar`, { body: form as never, bodySerializer: (b: unknown) => b as never, headers: { "Idempotency-Key": key } }),
  );
}

export async function deleteAvatar(): Promise<WriteResult<unknown>> {
  if (MOCK) return (await mock()).deleteAvatar();
  return write((key) => looseApi.DELETE(`${P}/me/avatar`, { headers: { "Idempotency-Key": key } }));
}
