import type { Metadata } from "next";
import { Suspense } from "react";
import { PaymentScreen } from "@/components/web-booking/payment-screen";
import { getBranding } from "@/lib/api/server";

// Trang chứa token lượt giữ chỗ: không index, không cache (header `no-store` đặt ở next.config.ts).
export const metadata: Metadata = {
  title: "Thanh toán",
  robots: { index: false, follow: false },
};

export default function PaymentPage({ params }: PageProps<"/thanh-toan/[token]">) {
  return (
    <Suspense fallback={<p className="text-center text-muted">Đang tải thông tin thanh toán…</p>}>
      <PaymentLoader params={params} />
    </Suspense>
  );
}

async function PaymentLoader({ params }: Pick<PageProps<"/thanh-toan/[token]">, "params">) {
  const [{ token }, { phone }] = await Promise.all([params, getBranding()]);
  return <PaymentScreen token={token} hotline={phone} />;
}
