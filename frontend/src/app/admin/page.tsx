import { redirect } from "next/navigation";
import { adminMenuOrder, adminPerms } from "@/lib/api/server";
import { firstAllowedHref } from "./_components/forbidden";

// Vào khu quản trị (cả sau đăng nhập) ⇒ mục đầu tiên trong menu mà người này có quyền (Admin: Báo cáo & phân tích).
// Phiên lỗi đã được layout chuyển về đăng nhập.
export default async function AdminIndexPage() {
  const [perms, order] = await Promise.all([adminPerms(), adminMenuOrder()]);
  redirect(firstAllowedHref(perms, order));
}
