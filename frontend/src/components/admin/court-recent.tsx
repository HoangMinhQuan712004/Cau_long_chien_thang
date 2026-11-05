"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getTransactions } from "@/components/booking-engine/requests";
import type { TransactionRow } from "@/components/booking-engine/types";
import { StatusBadge } from "@/components/booking-engine/ui";
import { Skeleton } from "@/components/ui/skeleton";
import { addDaysIso, formatDayMonth, formatVnd, todayVn } from "@/lib/format";
import { SECTION, SECTION_TITLE } from "./court-overview";
import { t5 } from "./court-form-logic";

// Giao dịch gần đây của sân (30 ngày, tối đa 5 dòng) – mục cuối ngăn chi tiết.

const LIMIT = 5;

export function CourtRecent({ code }: { code: string }) {
  // undefined = đang tải, null = lỗi
  const [rows, setRows] = useState<TransactionRow[] | null | undefined>(undefined);

  useEffect(() => {
    let live = true;
    const today = todayVn();
    getTransactions({ resource: code, from: addDaysIso(today, -29), to: today })
      .then((res) => live && setRows(res.ok ? res.data.rows.slice(0, LIMIT) : null))
      .catch(() => live && setRows(null));
    return () => {
      live = false;
    };
  }, [code]);

  return (
    <section aria-labelledby="court-recent" className={SECTION}>
      <h3 id="court-recent" className={SECTION_TITLE}>Giao dịch gần đây (30 ngày)</h3>
      {rows === undefined ? (
        <Skeleton className="h-20 w-full" />
      ) : rows === null ? (
        <p className="text-sm text-danger">Không tải được giao dịch. Đóng ngăn rồi mở lại để thử lại.</p>
      ) : rows.length ? (
        <ul className="flex flex-col divide-y divide-border/60">
          {rows.map((r) => (
            <li key={r.code} className="flex items-start justify-between gap-3 py-2.5">
              <span className="flex min-w-0 flex-col">
                <span className="text-sm font-semibold tabular-nums">
                  {formatDayMonth(r.play_date)} · {t5(r.start_time)}–{t5(r.end_time)}
                </span>
                <span className="text-ui text-muted wrap-anywhere">{r.customer_name} · {formatVnd(r.amount)}</span>
              </span>
              <StatusBadge status={r.payment_status} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">Chưa có giao dịch trong 30 ngày qua.</p>
      )}
      <Link href="/admin/lich-su-giao-dich" className="inline-flex min-h-11 items-center self-start text-sm font-semibold text-primary hover:underline focus-ring sm:min-h-0">
        Xem lịch sử giao dịch ›
      </Link>
    </section>
  );
}
