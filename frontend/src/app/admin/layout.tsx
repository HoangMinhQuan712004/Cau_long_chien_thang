import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { FeedbackHost } from "@/components/feedback/feedback-host";
import { LogoutButton } from "@/components/logout-button";
import { getCurrentUser } from "@/lib/api/server";
import { site } from "@/lib/site";

export const metadata: Metadata = {
  title: { default: "Quản lý", template: `%s | Quản lý ${site.shortName}` },
  robots: { index: false, follow: false },
};

type Role = "admin" | "staff";

/** Menu theo vai: chủ sân thấy đủ; tài khoản quầy chỉ thấy phần đặt sân. Quyền thật do backend kiểm. */
const NAV: { href: string; label: string; roles: Role[] }[] = [
  { href: "/admin/dat-san", label: "Đặt sân", roles: ["admin", "staff"] },
  { href: "/admin/lich-su-giao-dich", label: "Lịch sử giao dịch", roles: ["admin"] },
  { href: "/admin/san", label: "Sân & bảng giá", roles: ["admin"] },
];

export default function AdminLayout({ children }: LayoutProps<"/admin">) {
  return (
    <>
      <Suspense fallback={<p className="p-8 text-muted">Đang tải…</p>}>
        <Shell>{children}</Shell>
      </Suspense>
      <FeedbackHost />
    </>
  );
}

/** Chỉ admin/staff được vào. Backend vẫn kiểm tra quyền trên từng API. */
async function Shell({ children }: { children: React.ReactNode }) {
  const user = await getCurrentUser();
  if (!user) redirect("/dang-nhap?next=/admin");
  if (user.role === "customer") redirect("/tai-khoan");
  const role: Role = user.role === "admin" ? "admin" : "staff";

  return (
    <div className="flex min-h-full flex-1 flex-col md:flex-row">
      <aside className="border-b border-border bg-surface p-4 md:w-56 md:border-r md:border-b-0">
        <Link href="/" className="font-bold text-primary">
          {site.shortName}
        </Link>
        <nav aria-label="Quản lý" className="mt-4 flex gap-4 text-sm md:flex-col md:gap-2">
          {NAV.filter((n) => n.roles.includes(role)).map((n) => (
            <Link key={n.href} href={n.href} className="hover:text-primary">
              {n.label}
            </Link>
          ))}
        </nav>
      </aside>
      <div className="min-w-0 flex-1 p-4 md:p-8">
        <div className="mb-6 flex items-center justify-end gap-4 text-sm text-muted">
          <span>
            {user.full_name} · {role === "admin" ? "Chủ sân" : "Tại máy"}
          </span>
          <LogoutButton />
        </div>
        {children}
      </div>
    </div>
  );
}
