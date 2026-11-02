import { redirect } from "next/navigation";
import { getAdminSession } from "@/lib/api/server";

// Trang vào khu quản trị (cả sau đăng nhập): Admin ⇒ Báo cáo & phân tích (BR-002); tài khoản quầy ⇒ Đặt sân.
// Phiên lỗi đã được layout chuyển về đăng nhập.
export default async function AdminIndexPage() {
  const session = await getAdminSession().catch(() => null);
  redirect(session?.ok && session.session.account.kind === "admin" ? "/admin/bao-cao" : "/admin/dat-san");
}
