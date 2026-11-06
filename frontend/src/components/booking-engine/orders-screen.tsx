"use client";

import { useCallback, useEffect, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { addDaysIso, formatDate, formatDayMonthYear, formatVnd } from "@/lib/format";
import { authFailure } from "./booking-dialogs";
import { ItemFlow } from "./item-flow";
import { OrderFlow } from "./order-flow";
import { getBookingOrders, sendCollectOrder } from "./requests";
import type { BookingOrderKind, BookingOrderList, BookingOrderRow, BookingOrderStatus } from "./types";
import { btnCls, btnPrimaryCls, ErrorBanner, inputCls, StatusBadge } from "./ui";

// /admin/don-dat-san (T-041, chỉ Admin): MỌI đơn đặt sân (quầy / online / định kỳ), không gồm vé sự kiện.
// Lọc Loại × Trạng thái + khoảng ngày chơi, tìm theo mã đơn / mã con / tên / SĐT, "Thu cả đơn" ngay trên dòng (chỉ thu một lần).

const DOW = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
const SIZE = 20;
const KINDS: { key: "all" | BookingOrderKind; label: string }[] = [
  { key: "all", label: "Tất cả" },
  { key: "single", label: "Ngày" },
  { key: "recurring", label: "Định kỳ" },
];
const STATUSES: { key: "all" | BookingOrderStatus; label: string }[] = [
  { key: "all", label: "Tất cả" },
  { key: "unpaid", label: "Chưa thanh toán" },
  { key: "paid", label: "Đã thanh toán" },
  { key: "uncollectible", label: "Không thu được" },
];
const pad = (n: number) => String(n).padStart(2, "0");
const dm = (d: string) => `${d.slice(8, 10)}/${d.slice(5, 7)}`;
const SOURCE: Record<string, string> = { counter: "Quầy", online: "Online" };

type Dialog = { kind: "order"; code: string; cancel?: boolean } | { kind: "item"; code: string } | { kind: "collect"; row: BookingOrderRow };

/** Chữ "sân chính (+n sân khác)" (đơn định kỳ có thể có buổi ở nhiều sân, T-043). */
const courtText = (o: BookingOrderRow) => {
  const others = new Set(o.resource_codes).size - 1;
  return `${o.resource_name}${others > 0 ? ` (+${others} sân khác)` : ""}`;
};

export function OrdersScreen({ today }: { today: string }) {
  const [kind, setKind] = useState<"all" | BookingOrderKind>("all");
  const [status, setStatus] = useState<"all" | BookingOrderStatus>("all");
  // Mặc định: 30 ngày gần nhất và sắp tới
  const [from, setFrom] = useState(addDaysIso(today, -30));
  const [to, setTo] = useState(addDaysIso(today, 30));
  const [input, setInput] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<BookingOrderList | null>(null);
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

  const rangeOk = Boolean(from && to && from <= to);

  const load = useCallback(async () => {
    if (!rangeOk) return;
    const res = await getBookingOrders({ kind: kind === "all" ? undefined : kind, status: status === "all" ? undefined : status, q: q || undefined, date_from: from, date_to: to, page, size: SIZE });
    if (res.ok) {
      setData(res.data);
      setError("");
    } else if (!authFailure(res.error)) setError(errorText(res.error));
  }, [kind, status, q, from, to, page, rangeOk]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải khi đổi bộ lọc / tìm / trang
    void load();
  }, [load]);

  async function collect(row: BookingOrderRow) {
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

  // Số đếm theo trạng thái trong phạm vi Loại đang lọc (counts[kind][status])
  const counts = data?.counts[kind];
  const pages = data ? Math.max(1, Math.ceil(data.total / data.size)) : 1;
  const chip = (active: boolean) => `rounded-full border px-3 py-1.5 text-sm ${active ? "border-primary bg-primary text-white" : "border-border bg-surface hover:bg-primary-softer"}`;
  const reset = () => setPage(1);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold sm:text-2xl">Đơn đặt sân</h1>

      <div className="space-y-3 rounded-xl border border-border bg-surface p-3 sm:p-4">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Lọc theo loại đơn">
            <span className="text-sm text-muted">Loại:</span>
            {KINDS.map((k) => (
              <button
                key={k.key}
                type="button"
                aria-pressed={kind === k.key}
                onClick={() => {
                  setKind(k.key);
                  reset();
                }}
                className={chip(kind === k.key)}
              >
                {k.label}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Lọc theo trạng thái">
            <span className="text-sm text-muted">Trạng thái:</span>
            {STATUSES.map((f) => (
              <button
                key={f.key}
                type="button"
                aria-pressed={status === f.key}
                onClick={() => {
                  setStatus(f.key);
                  reset();
                }}
                className={chip(status === f.key)}
              >
                {f.label}
                {counts ? ` (${counts[f.key]})` : ""}
              </button>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label htmlFor="ord-from" className="mb-1 block text-xs text-muted">
              Ngày chơi từ
            </label>
            <input
              id="ord-from"
              type="date"
              value={from}
              onChange={(e) => {
                setFrom(e.target.value);
                reset();
              }}
              className={`${inputCls} h-10 w-40`}
            />
          </div>
          <div>
            <label htmlFor="ord-to" className="mb-1 block text-xs text-muted">
              đến
            </label>
            <input
              id="ord-to"
              type="date"
              min={from}
              value={to}
              onChange={(e) => {
                setTo(e.target.value);
                reset();
              }}
              className={`${inputCls} h-10 w-40`}
            />
          </div>
          <div className="w-full sm:ml-auto sm:w-72">
            <label htmlFor="ord-search" className="sr-only">
              Tìm theo mã đơn, mã con, tên khách hoặc SĐT
            </label>
            <input id="ord-search" type="search" value={input} onChange={(e) => setInput(e.target.value)} placeholder="Tìm mã đơn, mã con, tên, SĐT…" className={`${inputCls} h-10`} />
          </div>
        </div>
        {!rangeOk ? <p role="alert" className="text-xs text-danger">Khoảng ngày không hợp lệ: “đến” phải sau hoặc bằng “từ”.</p> : null}
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
        <p className="rounded-lg border border-border bg-surface p-8 text-center text-muted">{q || status !== "all" || kind !== "all" ? "Không có đơn nào khớp bộ lọc." : "Chưa có đơn đặt sân nào trong khoảng ngày này."}</p>
      ) : (
        <ul className="space-y-3">
          {data.items.map((o) => (
            <li key={o.order_code} className="rounded-xl border border-border bg-surface p-4 shadow-card">
              <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                <button type="button" onClick={() => setDialog({ kind: "order", code: o.order_code })} className="min-w-0 text-left focus-ring" aria-label={`Mở đơn ${o.order_code}`}>
                  <span className="flex flex-wrap items-center gap-2">
                    <b className="font-mono text-sm">{o.order_code}</b>
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${o.kind === "recurring" ? "bg-blk-session text-blk-session-fg" : "bg-primary-softer text-primary"}`}>{o.kind === "recurring" ? "Định kỳ" : "Ngày"}</span>
                    <span className="rounded-full border border-border px-2 py-0.5 text-xs text-muted">{SOURCE[o.source]}</span>
                    <StatusBadge status={o.status} />
                  </span>
                  <span className="mt-1 block text-sm font-medium">
                    {o.customer_name}
                    {o.member_code ? <span className="ml-1.5 rounded bg-background px-1.5 py-0.5 font-mono text-xs font-normal text-muted">{o.member_code}</span> : null}
                    {o.phone_masked ? <span className="font-normal text-muted"> · {o.phone_masked}</span> : null}
                  </span>
                  {o.kind === "recurring" ? (
                    <>
                      <span className="block text-sm text-muted">
                        {courtText(o)} · {o.weekdays.map((d) => DOW[d - 1]).join(" ")} · {pad(o.start_hour)}:00–{pad(o.end_hour)}:00
                      </span>
                      <span className="block text-sm text-muted">
                        Từ buổi đầu {dm(o.date_from)} – buổi cuối {dm(o.date_to)}/{o.date_to.slice(0, 4)} · {o.sessions} buổi
                      </span>
                    </>
                  ) : (
                    <>
                      <span className="block text-sm text-muted">{courtText(o)}</span>
                      <span className="block text-sm text-muted">
                        {formatDayMonthYear(o.play_date)} · {o.blocks} khối
                      </span>
                    </>
                  )}
                </button>
                <div className="text-right">
                  <p className="text-lg font-bold tabular-nums">{formatVnd(o.total)}</p>
                  {o.kind === "recurring" && o.discount_pct > 0 ? <p className="text-xs text-muted">Giảm {o.discount_pct}% (gốc {formatVnd(o.original_amount)})</p> : null}
                  <p className="mt-1 text-xs text-muted">
                    {formatDate(o.created_at)}
                    {o.created_by ? ` · ${o.created_by}` : ""}
                  </p>
                  <div className="mt-2 flex flex-wrap justify-end gap-2">
                    {(o.status as string) !== "cancelled" ? ( // TODO(T-051): bỏ ép kiểu khi schema.d.ts có `cancelled`
                      <button type="button" onClick={() => setDialog({ kind: "order", code: o.order_code, cancel: true })} className={`${btnCls} border-danger text-danger enabled:hover:bg-danger/10`} aria-label={`Hủy đơn ${o.order_code}`}>
                        Hủy đơn
                      </button>
                    ) : null}
                    {o.status === "unpaid" ? (
                      <button type="button" onClick={() => setDialog({ kind: "collect", row: o })} className={btnPrimaryCls}>
                        Thu cả đơn
                      </button>
                    ) : null}
                  </div>
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
            Thu <b>{formatVnd(dialog.row.total)}</b> tiền mặt cho đơn <b className="font-mono">{dialog.row.order_code}</b> ({dialog.row.sessions} {dialog.row.kind === "recurring" ? "buổi" : "khối"}). Mọi khối thành Đã thanh toán, chỉ thu một lần.
          </p>
        </Modal>
      ) : null}
      {dialog?.kind === "order" ? (
        <OrderFlow key={`${dialog.code}-${dialog.cancel ? "cancel" : "view"}`} orderCode={dialog.code} startCancel={dialog.cancel} onClose={() => setDialog(null)} onChanged={() => void load()} onOpenItem={(code) => setDialog({ kind: "item", code })} />
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
