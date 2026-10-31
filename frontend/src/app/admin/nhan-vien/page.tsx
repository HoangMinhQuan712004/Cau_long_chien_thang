import type { Metadata } from "next";
import { Suspense } from "react";
import { Alert } from "@/components/ui/alert";
import { getDictionary } from "@/i18n/dictionaries";
import { authedApi, getAdminSession } from "@/lib/api/server";
import { StaffManager } from "./_components/staff-manager";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getDictionary()).staff.metaTitle };
}

export default function StaffPage({ searchParams }: PageProps<"/admin/nhan-vien">) {
  return (
    <Suspense fallback={<p className="text-muted">Đang tải…</p>}>
      <Staff searchParams={searchParams} />
    </Suspense>
  );
}

async function Staff({ searchParams }: Pick<PageProps<"/admin/nhan-vien">, "searchParams">) {
  const [dictionary, sp] = await Promise.all([getDictionary(), searchParams]);
  const t = { ...dictionary.staff, passwordRules: dictionary.passwordRules };
  // Hết phiên đã được StaffGate (layout) chuyển về màn đăng nhập
  const result = await getAdminSession().catch(() => null);
  if (!result?.ok) return null;

  // Nhân viên vào thẳng URL: báo không có quyền (backend vẫn trả 403 cho API /admin/staff)
  if (result.session.account.kind !== "admin") {
    return <Alert variant="error">{t.forbidden}</Alert>;
  }

  const api = await authedApi();
  const { data, error } = await api.GET("/api/v1/admin/staff");
  if (error || !data) return <Alert variant="error">{t.loadError}</Alert>;

  // ?ma=NV002 (link từ Lịch sử thao tác) ⇒ làm nổi bật dòng đó; mã lạ thì thôi
  const focusCode = typeof sp.ma === "string" ? sp.ma : null;
  return <StaffManager staff={data} focusCode={focusCode} t={t} />;
}
