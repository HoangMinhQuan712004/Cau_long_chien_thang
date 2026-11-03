"use client";

import { useCallback, useEffect, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatDate, formatVnd } from "@/lib/format";
import { authFailure } from "./booking-dialogs";
import { ItemFlow } from "./item-flow";
import { OrderFlow } from "./order-flow";
import { getRecurringOrders, sendCollectOrder } from "./requests";
import type { RecurringOrderList, RecurringOrderRow, RecurringOrderStatus } from "./types";
import { btnCls, btnPrimaryCls, ErrorBanner, inputCls, StatusBadge } from "./ui";

// /admin/don-dinh-ky (T-039, chỉ Admin): danh sách đơn định kỳ, lọc trạng thái + tìm, "Thu cả đơn" ngay trên dòng (chỉ thu một lần).

const DOW = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
const SIZE = 20;
const FILTERS: { key: "all" | RecurringOrderStatus; label: string }[] = [
  { key: "all", label: "Tất cả" },
  { key: "unpaid", label: "Chưa thanh toán" },
  { key: "paid", label: "Đã thanh toán" },
  { key: "uncollectible", label: "Không thu được" },
];
const pad = (n: number) => String(n).padStart(2, "0");
const dm = (d: string) => `${d.slice(8, 10)}/${d.slice(5, 7)}`;

type Dialog = { kind: "order"; code: string } | { kind: "item"; code: string } | { kind: "collect"; row: RecurringOrderRow };

export function RecurringOrdersScreen() {
  const [status, setStatus] = useState<"all" | RecurringOrderStatus>("all");
  const [input, setInput] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<RecurringOrderList | null>(null);
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");

  // Tìm: đợi người dùng dừng gõ 400 ms rồi mới gọi
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(input.trim());
      setPage(1);
    }, 400);
    return () => clearTimeout(t);
  }, [input]);

  const load = useCallback(async () => {
    const res = await getRecurringOrders({ status: status === "all" ? undefined : status, q: q || undefined, page, size: SIZE });
    if (res.ok) {
      setData(res.data);
      setError("");
    } else if (!authFailure(res.error)) setError(errorText(res.error));
  }, [status, q, page]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải khi đổi bộ lọc / tìm / trang
    void load();
  }, [load]);

  async function collect(row: RecurringOrderRow) {
    if (busy) return;
    setBusy(true);
    setBanner("");
    try {
      const res = await write((key) => sendCollectOrder(key, row.order_code));
      if (!res.ok) {
        if (!authFailure(res.error)) setBanner(errorText(res.error));
        return;
      }
      toast(`Đã thu ${formatVnd(row.total)}`, row.order_code);
      setDialog(null);
      await load();
    } finally {
      setBusy(false);
    }
  }

  const counts = data?.counts;
  const pages = data ? Math.max(1, Math.ceil(data.total / data.size)) : 1;
  const chip = (active: boolean) => `rounded-full border px-3 py-1.5 text-sm ${active ? "border-primary bg-primary text-white" : "border-border bg-surface hover:bg-primary-softer"}`;

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Đơn định kỳ</h1>

      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Lọc theo trạng thái">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            aria-pressed={status === f.key}
            onClick={() => {
              setStatus(f.key);
              setPage(1);
            }}
            className={chip(status === f.key)}
          >
            {f.label}
            {counts ? ` (${counts[f.key]})` : ""}
          </button>
        ))}
        <div className="ml-auto w-full sm:w-72">
          <label htmlFor="rec-search" className="sr-only">
            Tìm theo mã đơn, tên khách hoặc SĐT
          </label>
          <input id="rec-search" type="search" value={input} onChange={(e) => setInput(e.target.value)} placeholder="Tìm mã đơn, tên khách, SĐT…" className={inputCls} />
        </div>
      </div>

      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
      {error && !data ? (
        <div role="alert" className="space-y-2 rounded-lg border border-border bg-surface p-6 text-center text-sm">
          <p className="text-danger">{error}</p>
          <button type="button" onClick={() => void load()} className={btnCls}>
            Thử lại
          </button>
        </div>
      ) : !data ? (
        <p className="py-10 text-center text-muted" aria-busy>
          Đang tải…
        </p>
      ) : data.items.length === 0 ? (
        <p className="rounded-lg border border-border bg-surface p-8 text-center text-muted">{q || status !== "all" ? "Không có đơn nào khớp bộ lọc." : "Chưa có đơn định kỳ nào. Tạo ở màn Đặt sân → Đặt sân định kỳ."}</p>
      ) : (
        <ul className="space-y-3">
          {data.items.map((o) => (
            <li key={o.order_code} className="rounded-xl border border-border bg-surface p-4 shadow-card">
              <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                <button type="button" onClick={() => setDialog({ kind: "order", code: o.order_code })} className="min-w-0 text-left focus-ring" aria-label={`Mở đơn ${o.order_code}`}>
                  <span className="flex flex-wrap items-center gap-2">
                    <b className="font-mono text-sm">{o.order_code}</b>
                    <StatusBadge status={o.status} />
                  </span>
                  <span className="mt-1 block text-sm font-medium">
                    {o.customer_name}
                    {o.phone_masked ? <span className="font-normal text-muted"> · {o.phone_masked}</span> : null}
                  </span>
                  <span className="block text-sm text-muted">
                    {o.resource_name} · {o.weekdays.map((d) => DOW[d - 1]).join(" ")} · {pad(o.start_hour)}:00–{pad(o.end_hour)}:00
                  </span>
                  <span className="block text-sm text-muted">
                    Từ {dm(o.date_from)} đến {dm(o.date_to)}/{o.date_to.slice(0, 4)} · {o.sessions} buổi
                  </span>
                </button>
                <div className="text-right">
                  <p className="text-lg font-bold tabular-nums">{formatVnd(o.total)}</p>
                  {o.discount_pct > 0 ? <p className="text-xs text-muted">Giảm {o.discount_pct}% (gốc {formatVnd(o.original_amount)})</p> : null}
                  <p className="mt-1 text-xs text-muted">
                    {formatDate(o.created_at)}
                    {o.created_by ? ` · ${o.created_by}` : ""}
                  </p>
                  {o.status === "unpaid" ? (
                    <button type="button" onClick={() => setDialog({ kind: "collect", row: o })} className={`${btnPrimaryCls} mt-2`}>
                      Thu cả đơn
                    </button>
                  ) : null}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {data && pages > 1 ? (
        <nav aria-label="Phân trang" className="flex items-center justify-center gap-3">
          <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} className={btnCls}>
            ‹ Trước
          </button>
          <span className="text-sm text-muted" aria-live="polite">
            Trang {page}/{pages}
          </span>
          <button type="button" onClick={() => setPage((p) => Math.min(pages, p + 1))} disabled={page >= pages} className={btnCls}>
            Sau ›
          </button>
        </nav>
      ) : null}

      {dialog?.kind === "collect" ? (
        <Modal
          open
          onClose={() => setDialog(null)}
          title="Thu cả đơn"
          footer={
            <>
              <button type="button" onClick={() => setDialog(null)} className={btnCls} disabled={busy}>
                Hủy
              </button>
              <button type="button" onClick={() => void collect(dialog.row)} disabled={busy} className={btnPrimaryCls}>
                {busy ? "Đang thu…" : "Xác nhận đã thu"}
              </button>
            </>
          }
        >
          {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
          <p className="text-sm">
            Thu <b>{formatVnd(dialog.row.total)}</b> tiền mặt cho đơn <b className="font-mono">{dialog.row.order_code}</b> ({dialog.row.sessions} buổi). Mọi buổi thành Đã thanh toán, chỉ thu một lần.
          </p>
        </Modal>
      ) : null}
      {dialog?.kind === "order" ? (
        <OrderFlow key={dialog.code} orderCode={dialog.code} onClose={() => setDialog(null)} onChanged={() => void load()} onOpenItem={(code) => setDialog({ kind: "item", code })} />
      ) : null}
      {dialog?.kind === "item" ? (
        <ItemFlow
          key={dialog.code}
          code={dialog.code}
          onClose={() => setDialog(null)}
          onChanged={() => void load()}
          onOpenSession={() => {}}
          onOpenOrder={(code) => setDialog({ kind: "order", code })}
        />
      ) : null}
    </div>
  );
}
