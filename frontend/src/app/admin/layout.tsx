import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { LogoutButton } from "@/components/logout-button";
import { getCurrentUser } from "@/lib/api/server";
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

/** Chỉ admin/staff được vào. Backend vẫn kiểm tra quyền trên từng API. */
async function StaffGate({ children }: { children: React.ReactNode }) {
  const user = await getCurrentUser();
  if (!user) redirect("/dang-nhap?next=/admin");
  if (user.role === "customer") redirect("/tai-khoan");

  return (
    <>
      <div className="mb-6 flex items-center justify-end gap-4 text-sm text-muted">
        <span>
          {user.full_name} · {user.role === "admin" ? "Chủ sân" : "Nhân viên"}
        </span>
        <LogoutButton />
      </div>
      {children}
    </>
  );
}
