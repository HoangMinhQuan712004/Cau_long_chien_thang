import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { PageHeader } from "@/components/ui/page-header";
import { getDictionary } from "@/i18n/dictionaries";
import { getAdminSession } from "@/lib/api/server";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getDictionary()).auditLog.metaTitle };
}

export default function AuditLogPage() {
  return (
    <Suspense fallback={null}>
      <AuditLogShell />
    </Suspense>
  );
}

// Chỉ Admin (SRS Lịch sử thao tác BR-001); Tài khoản tại máy mở thẳng link ⇒ về Đặt sân. Backend vẫn kiểm quyền ở API.
async function AuditLogShell() {
  const [result, t] = await Promise.all([getAdminSession(), getDictionary()]);
  if (!result.ok || result.session.account.kind !== "admin") redirect("/admin/dat-san");
  return <PageHeader title={t.auditLog.title} description={t.auditLog.description} descriptionBelow />;
}
