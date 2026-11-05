import type { Metadata } from "next";
import { Suspense } from "react";
import { PaymentSettingsScreen } from "@/components/admin/payment-settings";
import type { BankOption, PaymentSettings } from "@/components/admin/payment-settings-types";
import { adminPerms, authedGetJson } from "@/lib/api/server";
import { getDictionary } from "@/i18n/dictionaries";
import { can } from "../../_components/forbidden";

export const metadata: Metadata = { title: "Cài đặt thanh toán", robots: { index: false, follow: false } };

export default function PaymentSettingsPage() {
  return (
    <Suspense fallback={<p className="text-muted">Đang tải…</p>}>
      <Loader />
    </Suspense>
  );
}

async function Loader() {
  // Thiếu quyền payments.settings ⇒ báo không có quyền, không gọi API (backend vẫn kiểm: 403 cũng báo như vậy)
  const [perms, { adminNav }] = await Promise.all([adminPerms(), getDictionary()]);
  const noPermission = adminNav.noPermission;
  if (!can(perms, "payments.settings")) return <p className="text-muted">{noPermission}</p>;
  const [settings, banks] = await Promise.all([
    authedGetJson<PaymentSettings>("/api/v1/payments/settings"),
    authedGetJson<BankOption[]>("/api/v1/payments/banks"),
  ]);
  if ((!settings.ok && [401, 403].includes(settings.status)) || (!banks.ok && [401, 403].includes(banks.status))) {
    return <p className="text-muted">{noPermission}</p>;
  }
  if (!settings.ok || !banks.ok) throw new Error("Không tải được cài đặt thanh toán");
  return <PaymentSettingsScreen initial={settings.data} banks={banks.data} />;
}
