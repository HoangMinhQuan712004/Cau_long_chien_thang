import type { Metadata } from "next";
import { Suspense } from "react";
import { TransactionsScreen } from "@/components/booking-engine/transactions-screen";
import type { Transactions } from "@/components/booking-engine/types";
import { authedApi, authedGetJson } from "@/lib/api/server";
import { addDaysIso, todayVn } from "@/lib/format";

export const metadata: Metadata = { title: "Lịch sử giao dịch" };

export default function TransactionsPage() {
  return (
    <Suspense fallback={<p className="text-muted">Đang tải…</p>}>
      <TransactionsLoader />
    </Suspense>
  );
}

async function TransactionsLoader() {
  const today = todayVn();
  const api = await authedApi();
  const [tx, resources] = await Promise.all([
    authedGetJson<Transactions>("/api/v1/booking/transactions", { from: addDaysIso(today, -6), to: today }),
    api.GET("/api/v1/booking/resources"),
  ]);

  // Chỉ Admin được xem Lịch sử giao dịch (tài khoản quầy → 403)
  if (!tx.ok && tx.status === 403) return <p className="text-muted">Chỉ chủ sân mới xem được mục này.</p>;
  if (!tx.ok || !resources.data) throw new Error("Không tải được lịch sử giao dịch");

  return (
    <TransactionsScreen
      initial={tx.data}
      resources={resources.data.items.map((r) => ({ code: r.code, name: r.name }))}
      today={today}
    />
  );
}
