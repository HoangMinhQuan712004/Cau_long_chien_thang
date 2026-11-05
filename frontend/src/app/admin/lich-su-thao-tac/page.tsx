import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton, SkeletonTable } from "@/components/ui/skeleton";
import { getDictionary } from "@/i18n/dictionaries";
import { adminMenuOrder, adminPerms, authedApi } from "@/lib/api/server";
import { can, FORBIDDEN_PARAM, firstAllowedHref } from "../_components/forbidden";
import { AuditLogScreen } from "./_components/audit-log-screen";
import { auditQuery, readAuditParams } from "./_components/audit-params";

const PATH = "/admin/lich-su-thao-tac";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getDictionary()).auditLog.metaTitle };
}

export default function AuditLogPage({ searchParams }: PageProps<"/admin/lich-su-thao-tac">) {
  return (
    <Suspense fallback={<AuditSkeleton />}>
      <AuditLogLoader searchParams={searchParams} />
    </Suspense>
  );
}

// Theo quyền audit_log.view (BR-001): thiếu quyền ⇒ về mục được phép + báo E-001; backend vẫn trả 403
async function AuditLogLoader({ searchParams }: Pick<PageProps<"/admin/lich-su-thao-tac">, "searchParams">) {
  const [t, sp, api, perms, order] = await Promise.all([getDictionary(), searchParams, authedApi(), adminPerms(), adminMenuOrder()]);
  const forbidden = `${firstAllowedHref(perms, order)}?${FORBIDDEN_PARAM}`;
  if (!can(perms, "audit_log.view")) redirect(forbidden);
  const params = readAuditParams(
    new URLSearchParams(Object.entries(sp).flatMap(([k, v]) => (typeof v === "string" ? [[k, v]] : []))),
  );
  const fail = { data: undefined, response: undefined };
  const [catalog, list] = await Promise.all([
    api.GET("/api/v1/admin/audit-log/catalog").catch(() => fail),
    api.GET("/api/v1/admin/audit-log", { params: { query: auditQuery(params) } }).catch(() => fail),
  ]);

  if (catalog.response?.status === 403 || list.response?.status === 403) redirect(forbidden);
  // Link sửa tay (ngày ngoài 12 tháng, loại lạ) ⇒ về mặc định
  if (list.response?.status === 422) redirect(PATH);
  if (!catalog.data) throw new Error("Không tải được danh mục lịch sử thao tác");

  return <AuditLogScreen catalog={catalog.data} data={list.data ?? null} applied={params} t={t.auditLog} />;
}

function AuditSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title={<Skeleton className="h-7 w-44" />}
        description={<Skeleton className="h-4 w-80 max-w-full" />}
        descriptionBelow
      />
      <Card bareOnMobile className="flex flex-col gap-3 sm:gap-4 sm:p-5">
        {/* Cùng hình khối thanh lọc: khoảng ngày, Người làm, Loại thao tác (từ xl một hàng) */}
        <div className="flex flex-col gap-3 xl:flex-row">
          <Skeleton className="h-8 rounded-lg sm:h-9.5 sm:w-98" />
          {/* Điện thoại: hàng ô chọn vuốt ngang ⇒ cắt phần thừa, không tràn trang */}
          <div className="flex gap-2 overflow-hidden">
            <Skeleton className="h-8 w-48 shrink-0 rounded-lg sm:h-9.5" />
            <Skeleton className="h-8 w-64 shrink-0 rounded-lg sm:h-9.5 2xl:w-78" />
          </div>
        </div>
        <SkeletonTable rows={8} cols={5} />
      </Card>
    </div>
  );
}
