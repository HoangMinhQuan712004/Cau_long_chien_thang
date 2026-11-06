import type { Metadata } from "next";
import { Suspense } from "react";
import { Alert } from "@/components/ui/alert";
import { getDictionary } from "@/i18n/dictionaries";
import { adminMenuOrder, adminPerms, authedApi } from "@/lib/api/server";
import { can } from "../../_components/forbidden";
import { SettingsShell, SettingsSkeleton } from "../_components/settings-nav";
import { MenuOrderEditor } from "./_components/menu-order-editor";
import { RolesEditor } from "./_components/roles-editor";

// Hai mục của màn Cài đặt (chỉ Admin) dùng chung trang này: Phân quyền nhân viên và Sắp xếp menu (?tab=menu), Back / F5 đúng.
// Mỗi mục giữ editor + thanh chưa lưu + UnsavedGuard riêng; đổi mục khi chưa lưu ⇒ UnsavedGuard hỏi (link khác tham số).

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getDictionary()).accessSettings.metaTitle, robots: { index: false, follow: false } };
}

export default function AccessSettingsPage({ searchParams }: PageProps<"/admin/cai-dat/phan-quyen">) {
  return (
    <Suspense fallback={<SettingsSkeleton />}>
      <AccessSettings searchParams={searchParams} />
    </Suspense>
  );
}

async function AccessSettings({ searchParams }: Pick<PageProps<"/admin/cai-dat/phan-quyen">, "searchParams">) {
  const [dictionary, perms, sp] = await Promise.all([getDictionary(), adminPerms(), searchParams]);
  const { settingsPage: t, adminNav } = dictionary;
  const tab = sp.tab === "menu" ? "menu" : "roles";
  // Thiếu quyền ⇒ chỉ dòng báo, không gọi API (backend vẫn chặn: 403)
  if (!can(perms, tab === "menu" ? "settings.menu" : "roles.manage")) return <p className="
    text-muted
  ">{adminNav.noPermission}</p>;

  return (
    <SettingsShell perms={perms} active={tab} t={t}>
      {tab === "menu" ? <MenuTab /> : <RolesTab />}
    </SettingsShell>
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
