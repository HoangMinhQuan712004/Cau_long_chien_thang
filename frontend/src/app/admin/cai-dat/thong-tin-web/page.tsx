import type { Metadata } from "next";
import { updateTag } from "next/cache";
import { Suspense } from "react";
import { Alert } from "@/components/ui/alert";
import { Card } from "@/components/ui/card";
import { getDictionary } from "@/i18n/dictionaries";
import { adminPerms, authedApi, getBranding } from "@/lib/api/server";
import { adminBrand } from "@/lib/site";
import { can } from "../../_components/forbidden";
import { SettingsShell, SettingsSkeleton } from "../_components/settings-nav";
import { LogoSection } from "./_components/logo-section";
import { SiteInfoForm } from "./_components/site-info-form";

// Thông tin web (chỉ Admin, quyền settings.site): logo (lưu ngay khi cắt xong), tên sân, địa chỉ + bản đồ, hotline, email (nút Lưu).

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getDictionary()).settingsPage.items.info.label, robots: { index: false, follow: false } };
}

/** Sau khi đổi logo / thông tin: xóa cache để trang khách thấy ngay (updateTag: lần tải kế tiếp đọc mới, không trả bản cũ). */
async function refreshBranding(tag: string) {
  "use server";
  if (!can(await adminPerms(), "settings.site")) return;
  updateTag(tag);
}

export default function SiteInfoPage() {
  return (
    <Suspense fallback={<SettingsSkeleton />}>
      <SiteInfo />
    </Suspense>
  );
}

async function SiteInfo() {
  const [{ siteInfo: t, siteLogo, settingsPage, adminNav }, perms] = await Promise.all([getDictionary(), adminPerms()]);
  // Thiếu quyền ⇒ chỉ dòng báo (backend vẫn chặn: 403)
  if (!can(perms, "settings.site")) return <p className="text-muted">{adminNav.noPermission}</p>;
  const api = await authedApi();
  const [{ data, response }, { logo_url: logoUrl }] = await Promise.all([api.GET("/api/v1/admin/site/info"), getBranding()]);
  if (response.status === 403) return <p className="text-muted">{adminNav.noPermission}</p>;
  return (
    <SettingsShell perms={perms} active="info" t={settingsPage}>
      <Card className="flex flex-col gap-6 p-4 lg:p-6">
        <LogoSection url={logoUrl} refresh={refreshBranding} brandDark={adminBrand(adminNav.brand, data?.name ?? "")} brandLight={data?.name ?? ""} t={siteLogo} />
        {/* key = version: tải lại sau khi máy khác đã lưu ⇒ form dựng mới từ bản đó */}
        {data ? <SiteInfoForm key={data.version} initial={data} refresh={refreshBranding} t={t} /> : <Alert variant="error">{t.loadError}</Alert>}
      </Card>
    </SettingsShell>
  );
}
