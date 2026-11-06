import type { Metadata } from "next";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { FeedbackHost } from "@/components/feedback/feedback-host";
import { getDictionary } from "@/i18n/dictionaries";
import { type AdminSessionError, getAdminSession, getBranding } from "@/lib/api/server";
import { adminBrand } from "@/lib/site";
import { AdminShell } from "./_components/admin-shell";
import { MENU_COLLAPSED, MENU_COOKIE } from "./_components/menu-cookie";

export async function generateMetadata(): Promise<Metadata> {
  const { name } = await getBranding();
  return {
    title: { default: "Quản trị", template: `%s | Quản trị ${name}` },
    robots: { index: false, follow: false },
  };
}

// Lý do hết phiên ⇒ câu giải thích ở màn đăng nhập (?ly-do=…): hết 12 giờ, đổi mật khẩu, Admin khóa tài khoản
const REASON_PARAM: Partial<Record<AdminSessionError, string>> = {
  expired: "het-han",
  password_changed: "doi-mat-khau",
  account_disabled: "tai-khoan-khoa",
};

export default function AdminLayout({ children }: LayoutProps<"/admin">) {
  return (
    <>
      <Suspense fallback={<ShellSkeleton />}>
        <Shell>{children}</Shell>
      </Suspense>
      <FeedbackHost />
    </>
  );
}

// Khung xám đúng hình sidebar + header + vùng nội dung trong lúc kiểm phiên (không nhảy layout)
function ShellSkeleton() {
  return (
    <div aria-hidden className="flex min-h-full flex-1 flex-col">
      <div className="h-14 shrink-0 bg-sidebar" />
      <div className="flex flex-1">
        <div className="hidden w-60 shrink-0 border-r bg-surface lg:block" />
        <div className="flex-1 px-4 py-4 lg:px-6 lg:py-5">
          <div className="h-8 w-40 animate-pulse rounded-lg bg-border motion-reduce:animate-none" />
        </div>
      </div>
    </div>
  );
}

/** Chỉ phiên quản trị (cookie admin_session) còn hiệu lực được vào. Backend vẫn kiểm tra quyền trên từng API. */
async function Shell({ children }: { children: React.ReactNode }) {
  const result = await getAdminSession().catch(() => null);
  if (!result?.ok) {
    const reason = result ? REASON_PARAM[result.reason] : undefined;
    redirect(`/dang-nhap?next=/admin${reason ? `&ly-do=${reason}` : ""}`);
  }
  const { account, avatar_url: avatarUrl, perms, menu_order: menuOrder } = result.session;
  const [t, { name: siteName, logo_url: logoUrl }, cookieStore] = await Promise.all([
    getDictionary(),
    getBranding(),
    // Lựa chọn thu gọn menu (đọc trong phần động đã nằm trong Suspense)
    cookies(),
  ]);

  return (
    <AdminShell
      perms={perms}
      menuOrder={menuOrder}
      name={account.display_name}
      avatarUrl={avatarUrl}
      logoUrl={logoUrl}
      brand={adminBrand(t.adminNav.brand, siteName)}
      roleLabel={account.role_label}
      initialCollapsed={cookieStore.get(MENU_COOKIE)?.value === MENU_COLLAPSED}
      t={t.adminNav}
    >
      {children}
    </AdminShell>
  );
}
