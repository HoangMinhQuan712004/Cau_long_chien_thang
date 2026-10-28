import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { LogoutButton } from "@/components/logout-button";
import { getDictionary } from "@/i18n/dictionaries";
import { type AdminSessionError, getAdminSession } from "@/lib/api/server";
import { site } from "@/lib/site";

export const metadata: Metadata = {
  title: { default: "Quản lý", template: `%s | Quản lý ${site.shortName}` },
  robots: { index: false, follow: false },
};

const NAV = [
  { href: "/admin", label: "Lịch đặt sân" },
  { href: "/admin/san", label: "Sân & bảng giá" },
];

export default function AdminLayout({ children }: LayoutProps<"/admin">) {
  return (
    <div className="flex min-h-full flex-1 flex-col md:flex-row">
      <aside className="border-b border-border bg-surface p-4 md:w-56 md:border-r md:border-b-0">
        <Link href="/" className="font-bold text-primary">
          {site.shortName}
        </Link>
        <nav aria-label="Quản lý" className="mt-4 flex gap-4 text-sm md:flex-col md:gap-2">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} className="hover:text-primary">
              {n.label}
            </Link>
          ))}
          <Suspense>
            <AdminOnlyNav />
          </Suspense>
        </nav>
      </aside>
      <div className="flex-1 p-4 md:p-8">
        <Suspense fallback={<p className="text-muted">Đang tải…</p>}>
          <StaffGate>{children}</StaffGate>
        </Suspense>
      </div>
    </div>
  );
}

// Lý do hết phiên ⇒ thông báo trên màn đăng nhập (E-007 hết 12 giờ, E-006 đổi mật khẩu, Admin khóa tài khoản)
const REASON_PARAM: Partial<Record<AdminSessionError, string>> = {
  expired: "het-han",
  password_changed: "doi-mat-khau",
  account_disabled: "tai-khoan-khoa",
};

/** Mục chỉ Admin thấy (nhân viên không thấy; trang vẫn tự kiểm quyền). */
async function AdminOnlyNav() {
  const result = await getAdminSession().catch(() => null);
  if (!result?.ok || result.session.account.kind !== "admin") return null;
  const t = (await getDictionary()).staff;
  return (
    <Link href="/admin/nhan-vien" className="hover:text-primary">
      {t.nav}
    </Link>
  );
}

/** Chỉ phiên quản trị còn hiệu lực được vào. Backend vẫn kiểm tra quyền trên từng API. */
async function StaffGate({ children }: { children: React.ReactNode }) {
  const result = await getAdminSession().catch(() => null);
  if (!result?.ok) {
    const reason = result ? REASON_PARAM[result.reason] : undefined;
    redirect(`/dang-nhap?next=/admin${reason ? `&ly-do=${reason}` : ""}`);
  }
  const { account } = result.session;

  return (
    <>
      <div className="mb-6 flex items-center justify-end gap-4 text-sm text-muted">
        <span>
          {account.display_name} · {account.role_label}
        </span>
        <LogoutButton area="admin" />
      </div>
      {children}
    </>
  );
}
