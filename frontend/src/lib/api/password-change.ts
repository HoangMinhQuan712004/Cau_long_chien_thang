import "client-only";
import { api, errorDetail, errorMessage } from "./client";

// Đổi mật khẩu lần đầu (T-015: tài khoản hội viên, mật khẩu ban đầu = SĐT)

export type ChangePasswordResult = { ok: true } | { ok: false; status?: number; code?: string; message?: string };

// Cờ `must_change_password` còn bật ⇒ không cần mật khẩu hiện tại; thành công BE cấp lại cookie phiên
export async function changeInitialPassword(newPassword: string): Promise<ChangePasswordResult> {
  try {
    const { error, response } = await api.POST("/api/v1/auth/password/change", { body: { new_password: newPassword } });
    if (response.ok) return { ok: true };
    // 422: sai quy tắc / trùng SĐT ⇒ câu của backend
    return { ok: false, status: response.status, code: errorDetail(error).code, message: errorMessage(error, "") || undefined };
  } catch {
    return { ok: false };
  }
}
