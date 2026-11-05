import type { Metadata } from "next";
import { Suspense } from "react";
import { Alert } from "@/components/ui/alert";
import { NavTabs } from "@/components/ui/nav-tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { getDictionary } from "@/i18n/dictionaries";
import { adminMenuOrder, adminPerms, authedApi } from "@/lib/api/server";
import { can } from "../../_components/forbidden";
import { MenuOrderEditor } from "./_components/menu-order-editor";
import { RolesEditor } from "./_components/roles-editor";

// Phân quyền & menu (chỉ Admin): 2 tab trên URL (?tab=menu) để Back chạy đúng.
// Mỗi tab giữ editor + thanh chưa lưu + UnsavedGuard riêng; đổi tab khi chưa lưu ⇒ UnsavedGuard hỏi (link khác tham số).

const PATH = "/admin/cai-dat/phan-quyen";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getDictionary()).accessSettings.metaTitle, robots: { index: false, follow: false } };
}

export default function AccessSettingsPage({ searchParams }: PageProps<"/admin/cai-dat/phan-quyen">) {
  return (
    <Suspense fallback={<AccessSkeleton />}>
      <AccessSettings searchParams={searchParams} />
    </Suspense>
  );
}

function AccessSkeleton() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-10 w-72 max-w-full" />
      <Skeleton className="h-96 w-full rounded-card" />
    </div>
  );
}

async function AccessSettings({ searchParams }: Pick<PageProps<"/admin/cai-dat/phan-quyen">, "searchParams">) {
  const [dictionary, perms, sp] = await Promise.all([getDictionary(), adminPerms(), searchParams]);
  const { accessSettings: t, adminNav } = dictionary;
  // Thiếu quyền ⇒ chỉ dòng báo, không gọi API (backend vẫn chặn: 403)
  if (!can(perms, "roles.manage")) return <p className="text-muted">{adminNav.noPermission}</p>;
  const tab = sp.tab === "menu" ? "menu" : "roles";

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-xl font-bold sm:text-2xl">{t.title}</h1>
        <p className="max-w-prose text-ui text-muted">{t.intro}</p>
      </div>
      <NavTabs
        label={t.title}
        active={tab}
        scroll={false}
        items={[
          { id: "roles", href: PATH, label: t.tabRoles },
          { id: "menu", href: `${PATH}?tab=menu`, label: t.tabMenu },
        ]}
      />
      {tab === "menu" ? <MenuTab /> : <RolesTab />}
    </div>
  );
}

/** Tab Phân quyền nhân viên: tải ma trận quyền khi mở tab. */
async function RolesTab() {
  const [{ roles: t, adminNav }, api] = await Promise.all([getDictionary(), authedApi()]);
  const { data, response } = await api.GET("/api/v1/admin/roles");
  if (response.status === 403) return <p className="text-muted">{adminNav.noPermission}</p>;
  if (!data) return <Alert variant="error">{t.loadError}</Alert>;
  return <RolesEditor initial={data} t={t} />;
}

/** Tab Thứ tự menu: thứ tự chung lấy từ phiên (menu_order). */
async function MenuTab() {
  const [{ menuOrder: t, adminNav }, perms, order] = await Promise.all([getDictionary(), adminPerms(), adminMenuOrder()]);
  if (!can(perms, "settings.menu")) return <p className="text-muted">{adminNav.noPermission}</p>;
  return <MenuOrderEditor initial={order} labels={adminNav.items} t={t} />;
}
