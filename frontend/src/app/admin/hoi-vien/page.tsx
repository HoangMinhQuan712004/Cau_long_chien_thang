import type { Metadata } from "next";
import { Suspense } from "react";
import { Alert } from "@/components/ui/alert";
import { PageHeader } from "@/components/ui/page-header";
import { type Dictionary, getDictionary } from "@/i18n/dictionaries";
import { adminPerms, authedApi, type MemberTierFilter } from "@/lib/api/server";
import { can } from "../_components/forbidden";
import { MemberList } from "./_components/member-list";
import { readMemberParams } from "./_components/member-params";
import { MemberSkeleton } from "./_components/member-skeleton";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getDictionary()).members.metaTitle };
}

export default function MembersPage({ searchParams }: PageProps<"/admin/hoi-vien">) {
  return (
    <Suspense fallback={<MemberSkeleton />}>
      <MembersShell searchParams={searchParams} />
    </Suspense>
  );
}

// Chữ (cookie ngôn ngữ) + quyền có rất nhanh ⇒ kiểm quyền trước (thiếu quyền: chỉ dòng báo, không chớp tiêu đề), rồi tiêu đề
// hiện trước, danh sách chờ API trong Suspense riêng
async function MembersShell({ searchParams }: Pick<PageProps<"/admin/hoi-vien">, "searchParams">) {
  const [{ members: t }, perms] = await Promise.all([getDictionary(), adminPerms()]);
  if (!can(perms, "member.manage")) return <Alert variant="error">{t.forbidden}</Alert>;
  return (
    <Suspense fallback={<MemberSkeleton title={t.title} label={t.listLoading} />}>
      <Members searchParams={searchParams} t={t} />
    </Suspense>
  );
}

// Đọc bộ lọc trên URL rồi lấy danh sách từ API (backend vẫn kiểm quyền: 403 ⇒ báo không có quyền)
async function Members({ searchParams, t }: Pick<PageProps<"/admin/hoi-vien">, "searchParams"> & { t: Dictionary["members"] }) {
  const sp = await searchParams;
  const params = readMemberParams(new URLSearchParams(Object.entries(sp).flatMap(([k, v]) => (typeof v === "string" ? [[k, v]] : []))));
  const { filter } = params;
  const api = await authedApi();
  const { data, response } = await api
    .GET("/api/v1/members", {
      params: {
        query: {
          q: filter.q.trim() || undefined,
          kind: filter.kind === "all" ? undefined : filter.kind,
          status: filter.status === "all" ? undefined : filter.status,
          tier: filter.tier === "all" ? undefined : (filter.tier as MemberTierFilter),
          racket: filter.racket || undefined,
          sort: params.bookingsSort ? (`bookings_${params.bookingsSort}` as const) : undefined,
          page: params.page,
          size: params.size,
        },
      },
    })
    .catch(() => ({ data: undefined, response: undefined }));

  // Backend chặn (403) ⇒ chỉ dòng báo, không tiêu đề (như các trang khác); lỗi tải thường vẫn có tiêu đề
  if (response?.status === 403) return <Alert variant="error">{t.forbidden}</Alert>;
  if (!data) {
    return (
      <div className="flex flex-col gap-5">
        <PageHeader title={t.title} />
        <Alert variant="error">{t.loadError}</Alert>
      </div>
    );
  }
  return <MemberList data={data} t={t} />;
}
