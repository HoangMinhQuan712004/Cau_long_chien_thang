import type { Metadata } from "next";
import { Suspense } from "react";
import { PaymentSettingsScreen } from "@/components/admin/payment-settings";
import type { BankOption, PaymentSettings } from "@/components/admin/payment-settings-types";
import { authedGetJson } from "@/lib/api/server";

export const metadata: Metadata = { title: "Cài đặt thanh toán", robots: { index: false, follow: false } };

export default function PaymentSettingsPage() {
  return (
    <Suspense fallback={<p className="text-muted">Đang tải…</p>}>
      <Loader />
    </Suspense>
  );
}

async function Loader() {
  const [settings, banks] = await Promise.all([
    authedGetJson<PaymentSettings>("/api/v1/payments/settings"),
    authedGetJson<BankOption[]>("/api/v1/payments/banks"),
  ]);
  // Chỉ Admin (tài khoản quầy → 403); backend vẫn kiểm quyền thật.
  if ((!settings.ok && [401, 403].includes(settings.status)) || (!banks.ok && [401, 403].includes(banks.status))) {
    return <p className="text-muted">Chỉ chủ sân mới xem được mục này.</p>;
  }
  if (!settings.ok || !banks.ok) throw new Error("Không tải được cài đặt thanh toán");
  return <PaymentSettingsScreen initial={settings.data} banks={banks.data} />;
}
