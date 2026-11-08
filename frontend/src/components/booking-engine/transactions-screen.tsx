"use client";

import Link from "next/link";
import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { errorText } from "@/lib/api/write";
import { addDaysIso, formatDateTime, formatDayMonthYear, formatTime, formatVnd } from "@/lib/format";
import { getTransactions, type TransactionFilters } from "./requests";
import type { TransactionEntry, Transactions } from "./types";
import { inputCls } from "./ui";

// Lịch sử giao dịch = sổ tiền vào (T-057, ADR-014; chỉ Admin): mỗi dòng một lần nhận tiền (tiền mặt, chuyển khoản tại quầy,
// tiền SePay khớp đơn) hoặc một lần hoàn khi hủy. Lọc theo NGÀY NHẬN / HOÀN TIỀN. Màn chỉ xem: thu, Không thu được, hủy làm ở
// Đơn đặt sân (mã đơn có link sang) và popup trên lịch.

type Filters = {
  from: string;
  to: string;
  resource: string;
  kind: "" | "in" | "refund";
  method: "" | "cash" | "transfer";
  q: string;
  page: number;
};

const MAX_DAYS = 92;
const daysBetween = (a: string, b: string) => Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000);

/** Lỗi khoảng ngày kiểm ở client (server cũng kiểm: E-001). */
function rangeError(f: Filters): string {
  if (!f.from || !f.to) return "Chọn đủ Từ ngày và Đến ngày.";
  if (f.from > f.to) return "Từ ngày không được sau Đến ngày.";
  if (daysBetween(f.from, f.to) + 1 > MAX_DAYS) return `Chỉ xem được tối đa ${MAX_DAYS} ngày mỗi lần.`;
  return "";
}

const KIND_LABEL: Record<TransactionEntry["kind"], string> = { in: "Thu tiền", refund: "Hoàn tiền" };
const METHOD_LABEL: Record<TransactionEntry["method"], string> = { cash: "Tiền mặt", transfer: "Chuyển khoản" };
const SOURCE_LABEL: Record<TransactionEntry["source"], string> = { counter: "Tại quầy", counter_qr: "QR tại quầy", online: "Khách đặt online" };

/** Số tiền có dấu: thu "+150.000 đ", hoàn "−150.000 đ". */
const signed = (e: TransactionEntry) => `${e.kind === "refund" ? "−" : "+"}${formatVnd(e.amount)}`;

/** Nội dung ngắn: "3 buổi · Sân 1, Sân 2" / "2 vé · Sân 3". */
function contentText(e: TransactionEntry) {
  const tickets = e.items.filter((i) => i.kind === "ticket").length;
  const bookings = e.items.length - tickets;
  const parts = [bookings ? `${bookings} buổi` : "", tickets ? `${tickets} vé` : ""].filter(Boolean).join(" + ");
  const courts = [...new Set(e.items.map((i) => i.resource_name))];
  const courtText = courts.length > 2 ? `${courts.slice(0, 2).join(", ")} +${courts.length - 2}` : courts.join(", ");
  return [parts, courtText].filter(Boolean).join(" · ");
}

/** Mã đơn booking ⇒ link sang Đơn đặt sân (thao tác ở đó); vé (mã sự kiện) chỉ hiện chữ. */
function OrderCode({ e }: { e: TransactionEntry }) {
  if (!e.order_code) return <span className="text-muted">—</span>;
  const isBooking = e.items.some((i) => i.kind === "booking");
  return isBooking ? (
    <Link
      href={`/admin/don-dat-san?q=${encodeURIComponent(e.order_code)}`}
      className="font-mono text-xs whitespace-nowrap text-primary hover:underline focus-ring"
      title="Mở ở Đơn đặt sân"
    >
      {e.order_code}
    </Link>
  ) : (
    <span className="font-mono text-xs whitespace-nowrap">{e.order_code}</span>
  );
}

function KindBadge({ e }: { e: TransactionEntry }) {
  const tone = e.kind === "refund" ? "bg-danger-soft text-danger" : "bg-primary-softer text-primary";
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${tone}`}>{KIND_LABEL[e.kind]}</span>;
}

/** Các mục (buổi / vé) của một lần nhận tiền. */
function ItemList({ e }: { e: TransactionEntry }) {
  return (
    <ul className="divide-y divide-border rounded-md border border-border bg-background text-sm">
      {e.items.map((i) => (
        <li key={`${i.kind}-${i.code}`} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-3 py-2">
          <span className="font-mono text-xs">{i.code}</span>
          <span>{i.kind === "ticket" ? "Vé" : "Buổi"} · {i.resource_name}</span>
          <span className="text-muted tabular-nums">
            {formatDayMonthYear(i.play_date)} · {formatTime(i.start_at)} – {formatTime(i.end_at)}
          </span>
          <span className="ml-auto font-medium tabular-nums">{formatVnd(i.amount)}</span>
        </li>
      ))}
    </ul>
  );
}

function ExpandButton({ open, count, onClick, id }: { open: boolean; count: number; onClick: () => void; id: string }) {
  return (
    <button
      type="button"
      aria-expanded={open}
      aria-controls={id}
      onClick={onClick}
      className="relative inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs text-primary hover:bg-primary-softer focus-ring before:absolute before:-inset-2"
    >
      <svg viewBox="0 0 20 20" className={`size-4 transition-transform motion-reduce:transition-none ${open ? "rotate-180" : ""}`} fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
        <path d="m5 8 5 5 5-5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {open ? "Ẩn" : `Xem ${count} mục`}
    </button>
  );
}

export function TransactionsScreen({
  initial,
  from,
  to,
  resources,
  today,
}: {
  initial: Transactions;
  /** Khoảng ngày của `initial` (mặc định 7 ngày gần nhất). */
  from: string;
  to: string;
  resources: { code: string; name: string }[];
  /** Hôm nay (giờ Việt Nam). */
  today: string;
}) {
  const [filters, setFilters] = useState<Filters>({ from, to, resource: "", kind: "", method: "", q: "", page: 1 });
  const [data, setData] = useState(initial);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  // Dòng đang mở rộng, theo vị trí trong trang (API không trả id dòng sổ); tải trang / bộ lọc mới thì đóng hết
  const [open, setOpen] = useState<Set<number>>(() => new Set());
  const filtersRef = useRef(filters);
  const first = useRef(true);
  const rangeMsg = rangeError(filters);

  const run = useCallback(async (f: Filters) => {
    const q: TransactionFilters = { from: f.from, to: f.to, resource: f.resource, kind: f.kind, method: f.method, q: f.q.trim(), page: f.page };
    setLoading(true);
    const res = await getTransactions(q);
    setLoading(false);
    if (filtersRef.current !== f) return; // đã có bộ lọc mới hơn
    if (res.ok) {
      setData(res.data);
      setOpen(new Set());
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
  const toggle = (row: number) =>
    setOpen((s) => {
      const next = new Set(s);
      if (next.has(row)) next.delete(row);
      else next.add(row);
      return next;
    });

  const pages = Math.max(1, Math.ceil(data.total / Math.max(1, data.size)));
  const cards: { key: string; label: string; value: string; note?: string; tone?: string }[] = [
    { key: "net", label: "Thực thu", value: formatVnd(data.cards.net), note: "Tiền mặt + Chuyển khoản − Hoàn tiền" },
    { key: "cash", label: "Tiền mặt", value: formatVnd(data.cards.cash) },
    { key: "transfer", label: "Chuyển khoản", value: formatVnd(data.cards.transfer), note: "Gồm QR tại quầy và khách đặt online" },
    { key: "refund", label: "Hoàn tiền", value: data.cards.refund ? `−${formatVnd(data.cards.refund)}` : formatVnd(0), tone: data.cards.refund ? "text-danger" : "" },
  ];

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold sm:text-2xl">Lịch sử giao dịch</h1>
        <p className="mt-1 text-sm text-muted">
          Mỗi dòng là một lần nhận tiền hoặc hoàn tiền, theo ngày tiền về. Thu tiền, hủy đơn làm ở{" "}
          <Link href="/admin/don-dat-san" className="text-primary hover:underline focus-ring">
            Đơn đặt sân
          </Link>
          .
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {cards.map((c) => (
          <div key={c.key} className={`rounded-lg border border-border bg-surface p-3 sm:p-4 ${c.key === "net" ? "col-span-2 lg:col-span-1" : ""}`}>
            <p className="text-sm text-muted">{c.label}</p>
            <p className={`mt-1 text-lg font-bold tabular-nums sm:text-xl ${c.tone ?? ""}`}>{c.value}</p>
            {c.note ? <p className="text-xs text-muted">{c.note}</p> : null}
          </div>
        ))}
      </div>

      <div className="grid gap-3 rounded-lg border border-border bg-surface p-4 sm:grid-cols-2 lg:grid-cols-6">
        <Field label="Từ ngày (tiền về)">
          <input type="date" value={filters.from} max={today} onChange={(e) => set({ from: e.target.value })} className={inputCls} />
        </Field>
        <Field label="Đến ngày">
          <input type="date" value={filters.to} max={today} onChange={(e) => set({ to: e.target.value })} className={inputCls} />
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
        <Field label="Loại">
          <select value={filters.kind} onChange={(e) => set({ kind: e.target.value as Filters["kind"] })} className={inputCls}>
            <option value="">Tất cả</option>
            <option value="in">{KIND_LABEL.in}</option>
            <option value="refund">{KIND_LABEL.refund}</option>
          </select>
        </Field>
        <Field label="Phương thức">
          <select value={filters.method} onChange={(e) => set({ method: e.target.value as Filters["method"] })} className={inputCls}>
            <option value="">Tất cả</option>
            <option value="cash">{METHOD_LABEL.cash}</option>
            <option value="transfer">{METHOD_LABEL.transfer}</option>
          </select>
        </Field>
        <Field label="Tìm kiếm">
          <input
            type="search"
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
            onClick={() => set({ from: addDaysIso(today, -6), to: today, resource: "", kind: "", method: "", q: "" })}
            className="text-sm text-primary hover:underline focus-ring"
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

      <div className={loading ? "opacity-60" : ""} aria-busy={loading}>
        {data.items.length === 0 ? (
          <p className="rounded-lg border border-border bg-surface px-3 py-8 text-center text-sm text-muted">Không có khoản tiền nào trong bộ lọc này.</p>
        ) : (
          <>
            {/* Máy tính: bảng */}
            <div className="hidden overflow-x-auto rounded-lg border border-border bg-surface lg:block">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-muted">
                  <tr className="border-b border-border">
                    <th className="px-3 py-2 font-medium">Thời gian</th>
                    <th className="px-3 py-2 font-medium">Loại</th>
                    <th className="px-3 py-2 font-medium">Phương thức</th>
                    <th className="px-3 py-2 font-medium">Mã đơn</th>
                    <th className="px-3 py-2 font-medium">Khách</th>
                    <th className="px-3 py-2 font-medium">Nội dung</th>
                    <th className="px-3 py-2 font-medium">Người thu</th>
                    <th className="px-3 py-2 text-right font-medium">Số tiền</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((e, row) => {
                    const isOpen = open.has(row);
                    const panel = `tx-items-${row}`;
                    return (
                      <Fragment key={`${data.page}-${row}`}>
                        <tr className={`border-b border-border align-top ${isOpen ? "bg-primary-softer/50" : "hover:bg-primary-softer/40"}`}>
                          <td className="px-3 py-2.5 whitespace-nowrap tabular-nums">{formatDateTime(e.occurred_at)}</td>
                          <td className="px-3 py-2.5">
                            <KindBadge e={e} />
                          </td>
                          <td className="px-3 py-2.5">
                            {METHOD_LABEL[e.method]}
                            <span className="block text-xs text-muted">{SOURCE_LABEL[e.source]}</span>
                          </td>
                          <td className="px-3 py-2.5">
                            <OrderCode e={e} />
                          </td>
                          <td className="px-3 py-2.5">
                            {e.customer_name}
                            <span className="block text-xs text-muted tabular-nums">{e.customer_phone_masked ?? "—"}</span>
                          </td>
                          <td className="px-3 py-2.5">
                            {contentText(e)}
                            <span className="block">
                              <ExpandButton open={isOpen} count={e.items.length} onClick={() => toggle(row)} id={panel} />
                            </span>
                          </td>
                          <td className="px-3 py-2.5">{e.actor_label}</td>
                          <td className={`px-3 py-2.5 text-right font-semibold whitespace-nowrap tabular-nums ${e.kind === "refund" ? "text-danger" : ""}`}>{signed(e)}</td>
                        </tr>
                        {isOpen ? (
                          <tr id={panel} className="border-b border-border bg-primary-softer/30">
                            <td colSpan={8} className="px-3 pt-1 pb-3">
                              <ItemList e={e} />
                            </td>
                          </tr>
                        ) : null}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Điện thoại / tablet: thẻ */}
            <ul className="space-y-2 lg:hidden">
              {data.items.map((e, row) => {
                const isOpen = open.has(row);
                const panel = `tx-items-m-${row}`;
                return (
                  <li key={`${data.page}-${row}`} className="rounded-lg border border-border bg-surface p-3">
                    <div className="flex items-start justify-between gap-3">
                      {/* w-0 flex-1: tên dài không đẩy bề rộng tối thiểu của thẻ (trang không bị giãn ngang trên điện thoại) */}
                      <div className="w-0 min-w-0 flex-1 space-y-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <KindBadge e={e} />
                          <OrderCode e={e} />
                        </div>
                        <p className="truncate text-sm font-medium">
                          {e.customer_name}
                          {e.customer_phone_masked ? <span className="font-normal text-muted tabular-nums"> · {e.customer_phone_masked}</span> : null}
                        </p>
                        <p className="text-xs text-muted">{contentText(e)}</p>
                      </div>
                      <div className="shrink-0 text-right">
                        <p className={`font-bold tabular-nums ${e.kind === "refund" ? "text-danger" : ""}`}>{signed(e)}</p>
                        <p className="text-xs text-muted tabular-nums">{formatDateTime(e.occurred_at)}</p>
                      </div>
                    </div>
                    <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
                      <span>
                        {METHOD_LABEL[e.method]} · {SOURCE_LABEL[e.source]} · {e.actor_label}
                      </span>
                      <ExpandButton open={isOpen} count={e.items.length} onClick={() => toggle(row)} id={panel} />
                    </div>
                    {isOpen ? (
                      <div id={panel} className="mt-2">
                        <ItemList e={e} />
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </div>

      <nav aria-label="Phân trang" className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted">
          {data.total} khoản · trang {data.page}/{pages}
        </span>
        <div className="ml-auto flex gap-1">
          <button
            type="button"
            disabled={filters.page <= 1}
            onClick={() => setFilters((f) => ({ ...f, page: f.page - 1 }))}
            className="min-h-9 rounded-md border border-border px-3 py-1.5 focus-ring disabled:opacity-50"
          >
            Trước
          </button>
          <button
            type="button"
            disabled={filters.page >= pages}
            onClick={() => setFilters((f) => ({ ...f, page: f.page + 1 }))}
            className="min-h-9 rounded-md border border-border px-3 py-1.5 focus-ring disabled:opacity-50"
          >
            Sau
          </button>
        </div>
      </nav>
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
