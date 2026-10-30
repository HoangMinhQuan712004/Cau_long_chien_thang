// DỮ LIỆU GIẢ khu hội viên (T-016) – chỉ chạy khi NEXT_PUBLIC_MEMBER_AREA_MOCK=1. Xóa khi nối API thật.
import type { ApiError, WriteResult } from "@/lib/api/write";
import type { Read } from "./requests";
import type { MeInput, MemberMe } from "./types";

export const MOCK_ME: MemberMe = {
  member_code: "HV0123",
  full_name: "Nguyễn Văn Minh",
  short_name: "Minh",
  nickname: "Minh Smash",
  email: "minh.nguyen@gmail.com",
  phone: "0912345678",
  joined_at: "2026-03-05",
  tier: "Trung bình",
  racket: "Astrox 88D Pro",
  show_on_records: false,
  avatar_url: null,
  record_kmh: null,
  version: 1,
};

let me: MemberMe = { ...MOCK_ME };
const wait = (ms = 300) => new Promise((r) => setTimeout(r, ms));
const fail = (status: number, code: string, message: string, extra: Record<string, unknown> = {}): { ok: false; error: ApiError } => ({
  ok: false,
  error: { status, code, message, extra },
});

export async function getMe(): Promise<Read<MemberMe>> {
  await wait();
  return { ok: true, data: me };
}

export async function putMe(b: MeInput): Promise<WriteResult<MemberMe>> {
  await wait(500);
  // Kịch bản thử: biệt danh "conflict" giả lập quầy vừa sửa hồ sơ (E-HV-12); version trong kho tăng lên như thật
  if (b.nickname === "conflict") {
    me = { ...me, tier: "Khá", version: me.version + 1 };
    return fail(409, "E-HV-12", "Hồ sơ của bạn vừa được cập nhật ở nơi khác. Tải lại để xem bản mới nhất.");
  }
  if (b.version !== me.version) return fail(409, "E-HV-12", "Hồ sơ của bạn vừa được cập nhật ở nơi khác. Tải lại để xem bản mới nhất.");
  if (b.email?.toLowerCase() === "taken@example.com") {
    return fail(422, "E-HV-11", "Email đã được sử dụng.", { fields: [{ field: "email", code: "E-HV-11", message: "Email đã được sử dụng." }] });
  }
  const words = b.full_name.trim().split(/\s+/);
  me = {
    ...me,
    full_name: b.full_name.trim(),
    short_name: words[words.length - 1],
    nickname: b.nickname,
    email: b.email,
    tier: b.tier,
    racket: b.racket,
    show_on_records: b.show_on_records,
    version: me.version + 1,
  };
  return { ok: true, status: 200, data: me };
}

export async function putAvatar(file: Blob): Promise<WriteResult<{ avatar_url: string }>> {
  await wait(600);
  const avatar_url = URL.createObjectURL(file);
  me = { ...me, avatar_url };
  return { ok: true, status: 200, data: { avatar_url } };
}

export async function deleteAvatar(): Promise<WriteResult<unknown>> {
  await wait(300);
  me = { ...me, avatar_url: null };
  return { ok: true, status: 204, data: null };
}
