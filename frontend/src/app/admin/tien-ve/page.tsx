import type { Metadata } from "next";
import { Suspense } from "react";
import { BankTransactionsScreen } from "@/components/web-booking/bank-transactions-screen";
import type { BankTransaction } from "@/components/web-booking/types";
import { authedGetJson } from "@/lib/api/server";

export const metadata: Metadata = { title: "Tiền về cần xử lý" };

export default function BankTransactionsPage() {
  return (
    <Suspense fallback={<p className="text-muted">Đang tải…</p>}>
      <Loader />
    </Suspense>
  );
}

async function Loader() {
  const res = await authedGetJson<BankTransaction[]>("/api/v1/payments/bank-transactions", { needs_action: "true", limit: "100" });
  // Chỉ Admin (tài khoản quầy → 403); backend vẫn kiểm quyền thật.
  if (!res.ok && (res.status === 403 || res.status === 401)) return <p className="text-muted">Chỉ chủ sân mới xem được mục này.</p>;
  if (!res.ok) throw new Error("Không tải được danh sách tiền về");
  return <BankTransactionsScreen initial={res.data} />;
}
