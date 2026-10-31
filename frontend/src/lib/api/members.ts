import "client-only";
import { errorDetail, errorMessage } from "./client";

// Lỗi API hội viên ⇒ hiện ở đâu: dưới ô Họ tên / SĐT, hay thông báo chung
export type MemberFailure = {
  field: "full_name" | "phone" | null;
  code: string;
  message: string;
};

type ErrorTexts = { forbidden: string; outOfCodes: string; network: string; unknown: string };

// E-001 (thiếu/dài) có thể là tên hoặc SĐT: backend nói rõ trong câu ("họ tên"/"số điện thoại")
function fieldOf(code: string, message: string): MemberFailure["field"] {
  if (code === "E-002" || code === "E-018" || code === "E-MEM-1") return "phone";
  if (code === "E-001") return /điện thoại/i.test(message) ? "phone" : "full_name";
  return null;
}

/** Đọc lỗi của POST/PATCH hội viên; `response` thiếu ⇒ lỗi mạng. */
export function memberFailure(error: unknown, response: Response | undefined, t: ErrorTexts): MemberFailure {
  if (!response) return { field: null, code: "network", message: t.network };
  const detail = errorDetail(error);
  const code = detail.code ?? (response.status === 422 ? "E-001" : "unknown");
  const own: Record<string, string> = {
    "E-AUTH-2": t.forbidden,
    "E-MEM-4": t.outOfCodes,
  };
  // E-MEM-1 (SĐT đã có hồ sơ tạm), E-MEM-9 (đã sửa ở máy khác): dùng câu của BE
  const message = own[code] ?? errorMessage(error, t.unknown);
  return { field: fieldOf(code, message), code, message };
}

/** Gọi API, gom lỗi mạng (fetch ném) thành `{ response: undefined }`. */
export async function callMemberApi<T>(
  request: () => Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<{ data?: T; error?: unknown; response?: Response }> {
  try {
    return await request();
  } catch {
    return {};
  }
}
