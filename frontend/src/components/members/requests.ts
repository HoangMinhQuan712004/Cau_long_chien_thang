import "client-only";
import { looseApi } from "@/lib/api/client";
import { type ApiError, toApiError, type WriteResult, write } from "@/lib/api/write";
import type {
  MemberDetail,
  MemberEdit,
  MemberInput,
  MemberPatch,
  ProfileItem,
  ProfileList,
  ProfileQuery,
  RacketGroup,
  TempInput,
} from "./types";

// Lời gọi API màn Hội viên. Đọc → `Read<T>`; ghi → `write()` (Idempotency-Key, tự thử lại khi mất mạng).
// NEXT_PUBLIC_MEMBERS_MOCK=1 dùng dữ liệu giả trong bộ nhớ (chỉ để dựng giao diện khi API chưa có).

export type Read<T> = { ok: true; data: T } | { ok: false; error: ApiError };

const P = "/api/v1/members";
const MOCK = process.env.NEXT_PUBLIC_MEMBERS_MOCK === "1";
const mock = () => import("./mock");

async function read<T>(call: () => Promise<{ data?: unknown; error?: unknown; response: Response }>): Promise<Read<T>> {
  try {
    const { data, error, response } = await call();
    if (response.ok && data !== undefined) return { ok: true, data: data as T };
    return { ok: false, error: toApiError(error, response.status) };
  } catch {
    return { ok: false, error: { status: 0, code: "E-017", message: "Mất kết nối. Vui lòng thử lại.", extra: {} } };
  }
}

export async function listProfiles(q: ProfileQuery): Promise<Read<ProfileList>> {
  if (MOCK) return (await mock()).listProfiles(q);
  const query: Record<string, string> = { type: q.type, sort: q.sort, page: String(q.page) };
  if (q.q) query.q = q.q;
  // Hai ô lọc chỉ áp cho hội viên: chip Hồ sơ tạm thì bỏ qua (BR-003)
  if (q.type !== "temp" && q.status !== "all") query.status = q.status;
  if (q.type !== "temp" && q.tier) query.tier = q.tier;
  return read(() => looseApi.GET(`${P}/profiles`, { params: { query } }));
}

export async function getDetail(id: number): Promise<Read<MemberDetail>> {
  if (MOCK) return (await mock()).getDetail(id);
  return read(() => looseApi.GET(`${P}/profiles/{id}`, { params: { path: { id } } }));
}

/** Dữ liệu cho hộp Sửa: kèm SĐT đầy đủ. */
export async function getEdit(id: number): Promise<Read<MemberEdit>> {
  if (MOCK) return (await mock()).getEdit(id);
  return read(() => looseApi.GET(`${P}/profiles/{id}/edit`, { params: { path: { id } } }));
}

export async function getNextCode(): Promise<Read<{ code: string }>> {
  if (MOCK) return (await mock()).getNextCode();
  return read(() => looseApi.GET(`${P}/next-code`, {}));
}

export async function listRackets(): Promise<Read<RacketGroup[]>> {
  if (MOCK) return (await mock()).listRackets();
  return read(() => looseApi.GET(`${P}/rackets`, {}));
}

export async function createRacket(name: string): Promise<WriteResult<{ id: number; brand: string; name: string }>> {
  if (MOCK) return (await mock()).createRacket(name);
  return write((key) => looseApi.POST(`${P}/rackets`, { body: { name }, headers: { "Idempotency-Key": key } }));
}

export async function createMember(body: MemberInput): Promise<WriteResult<ProfileItem>> {
  if (MOCK) return (await mock()).createMember(body);
  return write((key) => looseApi.POST(`${P}/profiles`, { body, headers: { "Idempotency-Key": key } }));
}

export async function patchMember(id: number, body: MemberPatch): Promise<WriteResult<ProfileItem | { unchanged: true }>> {
  if (MOCK) return (await mock()).patchMember(id, body);
  return write((key) =>
    looseApi.PATCH(`${P}/profiles/{id}`, { params: { path: { id } }, body, headers: { "Idempotency-Key": key } }),
  );
}

export async function createTemp(body: TempInput): Promise<WriteResult<ProfileItem>> {
  if (MOCK) return (await mock()).createTemp(body);
  return write((key) => looseApi.POST(`${P}/temp-profiles`, { body, headers: { "Idempotency-Key": key } }));
}
