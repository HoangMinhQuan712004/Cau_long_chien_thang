import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";
import { TransactionsScreen } from "@/components/booking-engine/transactions-screen";
import type { Transactions } from "@/components/booking-engine/types";
import { adminPerms, authedApi, authedGetJson } from "@/lib/api/server";
import { getDictionary } from "@/i18n/dictionaries";
import { can } from "../_components/forbidden";
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
  // Thiếu quyền booking.transactions.view ⇒ báo không có quyền, không gọi API (backend vẫn kiểm: 403 cũng báo như vậy)
  const [perms, { adminNav }] = await Promise.all([adminPerms(), getDictionary()]);
  const noPermission = adminNav.noPermission;
  if (!can(perms, "booking.transactions.view")) return <p className="text-muted">{noPermission}</p>;
  const api = await authedApi(); // đọc cookie trước khi dùng giờ hiện tại
  await connection(); // giờ hiện tại chỉ dùng ở request, không prerender
  const today = todayVn();
  const from = addDaysIso(today, -6); // 7 ngày tiền về gần nhất (T-057)
  const [tx, resources] = await Promise.all([
    authedGetJson<Transactions>("/api/v1/booking/transactions", { from, to: today }),
    api.GET("/api/v1/booking/resources"),
  ]);

  if (!tx.ok && tx.status === 403) return <p className="text-muted">{noPermission}</p>;
  if (!tx.ok || !resources.data) throw new Error("Không tải được lịch sử giao dịch");

  return (
    <TransactionsScreen
      initial={tx.data}
      from={from}
      to={today}
      resources={resources.data.items.map((r) => ({ code: r.code, name: r.name }))}
      today={today}
    />
  );
}
