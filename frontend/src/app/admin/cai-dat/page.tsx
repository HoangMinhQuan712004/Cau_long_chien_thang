import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { getDictionary } from "@/i18n/dictionaries";
import { adminPerms } from "@/lib/api/server";
import { firstSettingsHref, SettingsShell, SettingsSkeleton } from "./_components/settings-nav";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getDictionary()).settingsPage.title, robots: { index: false, follow: false } };
}

export default function SettingsPage() {
  return (
    <Suspense fallback={<SettingsSkeleton />}>
      <Settings />
    </Suspense>
  );
}

// Màn đầu Cài đặt: danh sách mục. Không có quyền mục nào ⇒ về trang đầu khu quản trị
async function Settings() {
  const [{ settingsPage: t }, perms] = await Promise.all([getDictionary(), adminPerms()]);
  if (!firstSettingsHref(perms)) redirect("/admin");
  return <SettingsShell perms={perms} t={t} />;
}
