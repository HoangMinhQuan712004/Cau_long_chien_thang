"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { errorText } from "@/lib/api/write";
import { addDaysIso, formatDayMonthYear, formatVnd, hhmm } from "@/lib/format";
import { formatPhone } from "@/lib/phone";
import { ItemFlow } from "./item-flow";
import { getTransactions, type TransactionFilters } from "./requests";
import { SessionFlow } from "./session-flow";
import type { PaymentStatus, Transactions } from "./types";
import { inputCls, METHOD_LABEL, StatusBadge, STATUS_LABEL } from "./ui";

// Lịch sử giao dịch (chỉ Admin): lọc theo ngày chơi / sân / trạng thái / phương thức / tìm mã-tên-SĐT, 8 dòng mỗi trang, 3 thẻ tổng.

type Filters = { from: string; to: string; resource: string; status: string; method: string; q: string; page: number };
type Dialog = { kind: "item" | "session"; code: string } | null;

const MAX_DAYS = 92;
const daysBetween = (a: string, b: string) => Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000);

/** Lỗi khoảng ngày kiểm ở client (server cũng kiểm: E-016, E-020). */
function rangeError(f: Filters): string {
  if (f.from && f.to && f.from > f.to) return "Từ ngày không được sau Đến ngày.";
  if (f.from && f.to && daysBetween(f.from, f.to) + 1 > MAX_DAYS) return `Chỉ xem được tối đa ${MAX_DAYS} ngày mỗi lần.`;
  return "";
}

export function TransactionsScreen({
  initial,
  resources,
  today,
}: {
  initial: Transactions;
  resources: { code: string; name: string }[];
  /** Hôm nay (giờ Việt Nam) – mặc định lọc 7 ngày gần nhất. */
  today: string;
}) {
  const [filters, setFilters] = useState<Filters>({ from: initial.date_from, to: initial.date_to, resource: "", status: "", method: "", q: "", page: 1 });
  const [data, setData] = useState(initial);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState<Dialog>(null);
  const filtersRef = useRef(filters);
  const first = useRef(true);
  const rangeMsg = rangeError(filters);

  const run = useCallback(async (f: Filters) => {
    const q: TransactionFilters = {
      from: f.from,
      to: f.to,
      resource: f.resource,
      status: f.status,
      method: f.method,
      q: f.q.trim(),
      page: f.page,
    };
    setLoading(true);
    const res = await getTransactions(q);
    setLoading(false);
    if (filtersRef.current !== f) return; // đã có bộ lọc mới hơn
    if (res.ok) {
      setData(res.data);
      setError("");
    } else {
      setError(errorText(res.error));
    }
  }, []);

  // Tải lại sau khi bộ lọc đổi (tìm kiếm chờ 300 ms ngừng gõ)
  useEffect(() => {
    filtersRef.current = filters;
    if (first.current) {
      first.current = false;
      return;
    }
    if (rangeError(filters)) return;
    const t = setTimeout(() => void run(filters), 300);
    return () => clearTimeout(t);
  }, [filters, run]);

  const set = (p: Partial<Filters>) => setFilters((f) => ({ ...f, page: 1, ...p }));
  const reload = () => void run(filtersRef.current);

  const pages = Math.max(1, Math.ceil(data.total / data.page_size));
  const cards: [PaymentStatus, string][] = [
    ["paid", "Đã thanh toán"],
    ["unpaid", "Chưa thanh toán"],
    ["uncollectible", "Không thu được"],
  ];

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold sm:text-2xl">Lịch sử giao dịch</h1>

      <div className="grid gap-3 sm:grid-cols-3">
        {cards.map(([k, label]) => (
          <div key={k} className="rounded-lg border border-border bg-surface p-4">
            <p className="text-sm text-muted">{label}</p>
            <p className="mt-1 text-xl font-bold tabular-nums">{formatVnd(data.cards[k]?.amount ?? 0)}</p>
            <p className="text-xs text-muted">{data.cards[k]?.count ?? 0} giao dịch</p>
          </div>
        ))}
      </div>

      <div className="grid gap-3 rounded-lg border border-border bg-surface p-4 sm:grid-cols-2 lg:grid-cols-6">
        <Field label="Từ ngày">
          <input type="date" value={filters.from} max={today} onChange={(e) => set({ from: e.target.value })} className={inputCls} />
        </Field>
        <Field label="Đến ngày">
          <input type="date" value={filters.to} onChange={(e) => set({ to: e.target.value })} className={inputCls} />
        </Field>
        <Field label="Sân">
          <select value={filters.resource} onChange={(e) => set({ resource: e.target.value })} className={inputCls}>
            <option value="">Tất cả</option>
            {resources.map((r) => (
              <option key={r.code} value={r.code}>
                {r.code} · {r.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Trạng thái">
          <select value={filters.status} disabled={filters.method !== ""} onChange={(e) => set({ status: e.target.value })} className={inputCls}>
            <option value="">Tất cả</option>
            {(Object.keys(STATUS_LABEL) as PaymentStatus[]).map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Phương thức">
          {/* Chọn phương thức ⇒ chỉ lấy giao dịch Đã thanh toán (BR-020) */}
          <select
            value={filters.method}
            onChange={(e) => set({ method: e.target.value, status: e.target.value ? "paid" : "" })}
            className={inputCls}
          >
            <option value="">Tất cả</option>
            <option value="cash">{METHOD_LABEL.cash}</option>
            <option value="transfer">{METHOD_LABEL.transfer}</option>
          </select>
        </Field>
        <Field label="Tìm kiếm">
          <input
            value={filters.q}
            maxLength={50}
            placeholder="Mã, tên hoặc SĐT"
            onChange={(e) => set({ q: e.target.value })}
            className={inputCls}
          />
        </Field>
        {rangeMsg ? (
          <p role="alert" className="text-sm text-danger sm:col-span-2 lg:col-span-6">
            {rangeMsg}
          </p>
        ) : null}
        <div className="flex gap-2 sm:col-span-2 lg:col-span-6">
          <button
            type="button"
            onClick={() => set({ from: addDaysIso(today, -6), to: today, resource: "", status: "", method: "", q: "" })}
            className="text-sm text-primary hover:underline"
          >
            Đặt lại bộ lọc (7 ngày gần nhất)
          </button>
        </div>
      </div>

      {error ? (
        <p role="alert" className="rounded-md border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
          {error}
        </p>
      ) : null}

      <div className={`relative overflow-x-auto rounded-lg border border-border bg-surface ${loading ? "opacity-60" : ""}`} aria-busy={loading}>
        <table className="w-full min-w-[52rem] text-left text-sm">
          <thead className="text-xs text-muted">
            <tr className="border-b border-border">
              <th className="px-3 py-2 font-medium">Mã</th>
              <th className="px-3 py-2 font-medium">Giờ chơi</th>
              <th className="px-3 py-2 font-medium">Sân</th>
              <th className="px-3 py-2 font-medium">Khách</th>
              <th className="px-3 py-2 text-right font-medium">Số tiền</th>
              <th className="px-3 py-2 font-medium">Phương thức</th>
              <th className="px-3 py-2 font-medium">Trạng thái</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-muted">
                  Không có giao dịch nào trong bộ lọc này.
                </td>
              </tr>
            ) : (
              data.rows.map((r) => (
                <tr key={r.code} className="border-b border-border last:border-0 hover:bg-primary-softer">
                  <td className="px-3 py-2.5 font-mono text-xs">
                    <button type="button" onClick={() => setDialog({ kind: "item", code: r.code })} className="text-primary hover:underline">
                      {r.code}
                    </button>
                    {/* Booking: mã khối (mã con) kèm mã đơn (T-019 AC4) */}
                    {r.order_code ? <span className="block text-[11px] text-muted">Đơn {r.order_code}</span> : null}
                  </td>
                  <td className="px-3 py-2.5">
                    {formatDayMonthYear(r.play_date)}
                    <span className="block text-xs text-muted">
                      {hhmm(r.start_time)} – {hhmm(r.end_time)}
                    </span>
                  </td>
                  <td className="px-3 py-2.5">{r.resource_codes.join(", ")}</td>
                  <td className="px-3 py-2.5">
                    {r.customer_name}
                    <span className="block text-xs text-muted tabular-nums">{r.phone ? formatPhone(r.phone) : "—"}</span>
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{formatVnd(r.amount)}</td>
                  <td className="px-3 py-2.5">{r.payment_method ? METHOD_LABEL[r.payment_method] : "—"}</td>
                  <td className="px-3 py-2.5">
                    <StatusBadge status={r.payment_status} />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <nav aria-label="Phân trang" className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted">
          {data.total} giao dịch · trang {data.page}/{pages}
        </span>
        <div className="ml-auto flex gap-1">
          <button
            type="button"
            disabled={filters.page <= 1}
            onClick={() => setFilters((f) => ({ ...f, page: f.page - 1 }))}
            className="rounded-md border border-border px-3 py-1.5 disabled:opacity-50"
          >
            Trước
          </button>
          <button
            type="button"
            disabled={filters.page >= pages}
            onClick={() => setFilters((f) => ({ ...f, page: f.page + 1 }))}
            className="rounded-md border border-border px-3 py-1.5 disabled:opacity-50"
          >
            Sau
          </button>
        </div>
      </nav>

      {dialog?.kind === "item" ? (
        <ItemFlow key={dialog.code} code={dialog.code} onClose={() => setDialog(null)} onChanged={reload} onOpenSession={(code) => setDialog({ kind: "session", code })} />
      ) : null}
      {dialog?.kind === "session" ? (
        <SessionFlow
          key={dialog.code}
          code={dialog.code}
          onClose={() => setDialog(null)}
          onChanged={reload}
          onOpenTicket={(code) => setDialog({ kind: "item", code })}
        />
      ) : null}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium">{label}</span>
      {children}
    </label>
  );
}
