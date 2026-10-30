import "client-only";
import { errorDetail, errorMessage } from "./client";

// Lỗi API hội viên ⇒ hiện ở đâu: dưới ô Họ tên / SĐT, hay thông báo chung
export type MemberFailure = {
  field: "full_name" | "phone" | null;
  code: string;
  message: string;
  /** E-MEM-1: SĐT đang là hồ sơ tạm ⇒ form Thêm đề nghị nâng hồ sơ đó thành hội viên. */
  temp?: TempMatch;
};

export type TempMatch = { ref: string; fullName: string; bookings: number; nextCode: string };

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
  const detail = errorDetail(error) as ReturnType<typeof errorDetail> & {
    ref?: string;
    full_name?: string;
    bookings?: number;
    next_code?: string;
  };
  const code = detail.code ?? (response.status === 422 ? "E-001" : "unknown");
  const own: Record<string, string> = {
    "E-AUTH-2": t.forbidden,
    "E-MEM-4": t.outOfCodes,
  };
  // E-MEM-3 (đã là hội viên) dùng câu của BE vì có mã HV
  const message = own[code] ?? errorMessage(error, t.unknown);
  const temp: TempMatch | undefined =
    code === "E-MEM-1" && detail.ref
      ? { ref: detail.ref, fullName: detail.full_name ?? "", bookings: detail.bookings ?? 0, nextCode: detail.next_code ?? "" }
      : undefined;
  return { field: fieldOf(code, message), code, message, temp };
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
