import { cookies } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";
import { LogoutButton } from "@/components/logout-button";
import { getAdminSession, getCurrentUser } from "@/lib/api/server";

const linkCls = "rounded-lg px-3 py-1.5 text-sm font-medium whitespace-nowrap focus-ring";

/**
 * Góc tài khoản của header khách (T-013 AC23): chưa đăng nhập ⇒ Đăng nhập / Đăng ký;
 * khách đã đăng nhập ⇒ tên + menu (Tài khoản, Đăng xuất); Admin/nhân viên ⇒ lối vào khu quản lý.
 * Không có cookie phiên thì không gọi backend. Đọc cookie ⇒ phải đặt trong <Suspense>.
 */
export async function HeaderAccount() {
  const jar = await cookies();
  if (jar.has("admin_session")) {
    const result = await getAdminSession().catch(() => null);
    if (result?.ok) {
      return (
        <Link href="/admin" className={`${linkCls} border border-border hover:text-primary`}>
          Quản lý
        </Link>
      );
    }
  } else if (jar.has("access_token")) {
    const user = await getCurrentUser();
    // Còn mật khẩu ban đầu ⇒ chặn mọi trang khách cho tới khi đổi (T-015)
    if (user?.must_change_password) redirect("/doi-mat-khau");
    if (user) return <CustomerMenu name={user.full_name} isMember={(user as { is_member?: boolean }).is_member === true} />;
  }
  return (
    <div className="flex items-center gap-1">
      <Link href="/dang-nhap" className={`${linkCls} hover:text-primary`}>
        Đăng nhập
      </Link>
      <Link href="/dang-ky" className={`${linkCls} bg-primary text-white hover:bg-primary-hover`}>
        Đăng ký
      </Link>
    </div>
  );
}

// Menu không cần JS: <details> mở danh sách Khu hội viên (đã liên kết hồ sơ) / Tài khoản / Đăng xuất
function CustomerMenu({ name, isMember }: { name: string; isMember: boolean }) {
  return (
    <details className="group relative">
      <summary
        className={`${linkCls} flex max-w-40 cursor-pointer list-none items-center gap-1 border border-border hover:text-primary`}
      >
        <span className="truncate">{name}</span>
        <span aria-hidden className="text-xs">▾</span>
      </summary>
      <div className="absolute right-0 z-40 mt-1 flex min-w-40 flex-col gap-1 rounded-card bg-surface p-2 text-sm shadow-card ring-1 ring-border">
        {isMember ? (
          <Link href="/hoi-vien" className="rounded-lg px-3 py-2 font-medium text-primary hover:bg-primary-softer">
            Khu hội viên
          </Link>
        ) : null}
        <Link href="/tai-khoan" className="rounded-lg px-3 py-2 hover:bg-primary-softer">
          Tài khoản
        </Link>
        <div className="px-3 py-2">
          <LogoutButton />
        </div>
      </div>
    </details>
  );
}
