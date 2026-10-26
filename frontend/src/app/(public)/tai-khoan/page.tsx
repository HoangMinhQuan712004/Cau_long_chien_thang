import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { LogoutButton } from "@/components/logout-button";
import { getCurrentUser } from "@/lib/api/server";
import { phoneHref, site } from "@/lib/site";

export const metadata: Metadata = {
  title: "Tài khoản của tôi",
  robots: { index: false },
};

export default function AccountPage() {
  return (
    <Suspense fallback={<p className="text-muted">Đang tải…</p>}>
      <Account />
    </Suspense>
  );
}

async function Account() {
  const user = await getCurrentUser();
  if (!user) redirect("/dang-nhap?next=/tai-khoan");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Xin chào, {user.full_name}</h1>
          <p className="text-sm text-muted">{user.email}</p>
        </div>
        <div className="flex items-center gap-4">
          {user.role !== "customer" && (
            <Link href="/admin" className="text-sm text-primary">
              Trang quản lý →
            </Link>
          )}
          <LogoutButton />
        </div>
      </div>

      <section className="rounded-lg border border-border bg-surface p-4">
        <h2 className="text-lg font-semibold">Đặt sân</h2>
        <p className="mt-1 text-sm text-muted">
          Hiện chưa đặt sân trực tuyến. Vui lòng đặt tại quầy hoặc gọi{" "}
          <a href={phoneHref} className="font-medium text-primary">
            {site.phone}
          </a>
          .
        </p>
      </section>
    </div>
  );
}
