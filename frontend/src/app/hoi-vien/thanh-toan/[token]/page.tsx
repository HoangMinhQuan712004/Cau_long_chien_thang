import type { Metadata } from "next";
import { Suspense } from "react";
import { PaymentScreen } from "@/components/web-booking/payment-screen";
import { getBranding } from "@/lib/api/server";

export const metadata: Metadata = { title: "Thanh toán" };

// Trang thanh toán trong khung khu hội viên (cùng màn với /thanh-toan/[token], thêm nút Vào phòng sau khi đặt thành công).
export default function Page({ params }: PageProps<"/hoi-vien/thanh-toan/[token]">) {
  return (
    <Suspense fallback={<p className="p-8 text-center text-muted">Đang tải thông tin thanh toán…</p>}>
      <Loader params={params} />
    </Suspense>
  );
}

async function Loader({ params }: Pick<PageProps<"/hoi-vien/thanh-toan/[token]">, "params">) {
  const [{ token }, { phone }] = await Promise.all([params, getBranding()]);
  return (
    <div className="mx-auto max-w-6xl px-4 py-6 sm:py-8">
      <PaymentScreen token={token} hotline={phone} member />
    </div>
  );
}
