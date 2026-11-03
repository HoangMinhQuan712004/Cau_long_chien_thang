"use client";

import { useId, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatDayMonthYear, formatVnd } from "@/lib/format";
import { CustomerPicker, customerErrors, customerPayload, emptyCustomer, type CustomerState } from "./customer-picker";
import { authFailure } from "./booking-dialogs";
import { getRecurringPreview, sendCollectOrder, sendRecurring } from "./requests";
import type { Calendar, RecurringBody, RecurringConflict, RecurringPreview, RecurringResult } from "./types";
import { btnCls, btnPrimaryCls, ErrorBanner, Hint, inputCls, SummaryBox } from "./ui";

// Đặt sân định kỳ (T-035, chỉ Admin): các thứ trong tuần + khung giờ, từ ngày → đến ngày, % giảm.
// Luồng: nhập → Xem trước (bảng từng buổi + tiền, buổi lỗi tô đỏ) → Đặt n buổi (tất cả hoặc không) → kết quả có "Thu cả đơn".

const DOW = [
  [1, "T2"],
  [2, "T3"],
  [3, "T4"],
  [4, "T5"],
  [5, "T6"],
  [6, "T7"],
  [7, "CN"],
] as const;
/** Thứ ISO (1 = T2) của một ngày YYYY-MM-DD. */
const isoDow = (d: string) => ((new Date(`${d}T00:00:00Z`).getUTCDay() + 6) % 7) + 1;
const dowName = (d: string) => DOW.find(([n]) => n === isoDow(d))?.[1] ?? "";
const pad = (n: number) => String(n).padStart(2, "0");
const hh = (t: string) => t.slice(0, 5);
const MAX_DAYS = 92;
const addDays = (d: string, n: number) => new Date(Date.parse(`${d}T00:00:00Z`) + n * 864e5).toISOString().slice(0, 10);

const REASON: Record<string, string> = {
  booked: "Đã có người đặt",
  event: "Trùng sự kiện",
  hold: "Đang giữ chỗ online",
  closed: "Ngoài giờ mở cửa",
  inactive: "Sân ngừng hoạt động",
  past: "Giờ đã qua",
  no_price: "Chưa có bảng giá",
};
const reasonText = (r?: string | null) => (r ? (REASON[r] ?? r) : "");

type Props = {
  calendar: Calendar;
  today: string;
  onClose: () => void;
  /** Đã đặt (hoặc đã thu tiền): cha tải lại lịch và tô sáng đơn. */
  onChanged: (orderCode: string) => void;
  onOpenOrder: (orderCode: string) => void;
};

export function RecurringDialog({ calendar, today, onClose, onChanged, onOpenOrder }: Props) {
  const ids = { res: useId(), from: useId(), to: useId(), sh: useId(), eh: useId(), pct: useId() };
  const resources = calendar.resources.filter((r) => r.is_active);
  const first = calendar.columns[0] ?? 6;
  const last = (calendar.columns[calendar.columns.length - 1] ?? 21) + 1;

  const [customer, setCustomer] = useState<CustomerState>(emptyCustomer);
  const [resource, setResource] = useState(resources[0]?.code ?? "");
  const [weekdays, setWeekdays] = useState<number[]>([]);
  const [startHour, setStartHour] = useState(Math.min(first + 12, last - 1));
  const [endHour, setEndHour] = useState(Math.min(first + 14, last));
  const [dateFrom, setDateFrom] = useState(today);
  const [dateTo, setDateTo] = useState(addDays(today, 30));
  const [pct, setPct] = useState("0");
  const [preview, setPreview] = useState<RecurringPreview | null>(null);
  const [serverConflicts, setServerConflicts] = useState<RecurringConflict[]>([]);
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [done, setDone] = useState<(RecurringResult & { paid: boolean }) | null>(null);

  // Mọi thay đổi ở form làm bản xem trước cũ không còn đúng ⇒ phải xem trước lại trước khi đặt
  const edit = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setPreview(null);
    setServerConflicts([]);
    setBanner("");
  };

  const pctNum = pct.trim() === "" ? NaN : Number(pct);
  const cErr = customerErrors(customer);
  const formError =
    Object.keys(cErr).length > 0 ? "Vui lòng chọn khách." :
    !resource ? "Vui lòng chọn sân." :
    weekdays.length === 0 ? "Vui lòng chọn ít nhất một thứ trong tuần." :
    endHour <= startHour ? "Giờ kết thúc phải sau giờ bắt đầu." :
    !dateFrom || !dateTo || dateTo < dateFrom ? "Khoảng ngày không hợp lệ." :
    dateFrom < today ? "Từ ngày không được trước hôm nay." :
    dateTo > addDays(dateFrom, MAX_DAYS - 1) ? `Khoảng ngày tối đa ${MAX_DAYS} ngày.` :
    !Number.isInteger(pctNum) || pctNum < 0 || pctNum > 100 ? "% giảm là số nguyên từ 0 đến 100." : "";

  function body(): RecurringBody | null {
    const payload = customerPayload(customer);
    if (!payload || formError) return null;
    return { customer: payload, resource_code: resource, weekdays: [...weekdays].sort(), start_hour: startHour, end_hour: endHour, date_from: dateFrom, date_to: dateTo, discount_pct: pctNum };
  }

  async function runPreview() {
    setSubmitted(true);
    setBanner("");
    const b = body();
    if (!b) return;
    setBusy(true);
    try {
      const res = await getRecurringPreview(b);
      if (!res.ok) {
        if (!authFailure(res.error)) setBanner(errorText(res.error));
        return;
      }
      setPreview(res.data);
    } finally {
      setBusy(false);
    }
  }

  async function book() {
    const b = body();
    if (!b || !preview || preview.conflicts_count > 0 || busy) return;
    setBusy(true);
    setBanner("");
    try {
      const res = await write((key) => sendRecurring(key, b));
      if (!res.ok) {
        const e = res.error;
        if (authFailure(e)) return;
        if (e.code === "E-BOOK-5" && Array.isArray(e.extra.conflicts)) {
          // Có buổi không đặt được (kể cả tranh chấp đồng thời): không tạo gì; hiện danh sách buổi lỗi
          setServerConflicts(e.extra.conflicts as RecurringConflict[]);
          setPreview(null);
          setBanner(errorText(e));
          return;
        }
        setBanner(errorText(e));
        return;
      }
      const r = res.data as RecurringResult;
      setDone({ ...r, paid: false });
      onChanged(r.order_code);
      toast(`Đã đặt ${r.order_code}`, `${r.bookings.length} buổi · phải thu ${formatVnd(r.total)}`);
    } finally {
      setBusy(false);
    }
  }

  async function collect() {
    if (!done || busy) return;
    setBusy(true);
    setBanner("");
    try {
      const res = await write((key) => sendCollectOrder(key, done.order_code));
      if (!res.ok) {
        if (!authFailure(res.error)) setBanner(errorText(res.error));
        return;
      }
      setDone({ ...done, paid: true });
      onChanged(done.order_code);
      toast(`Đã thu ${formatVnd(done.total)}`, done.order_code);
    } finally {
      setBusy(false);
    }
  }

  // ---------------- Kết quả
  if (done) {
    return (
      <Modal
        open
        onClose={onClose}
        title="Đã đặt sân định kỳ"
        footer={
          <>
            <button type="button" onClick={onClose} className={btnCls}>
              Đóng
            </button>
            <button type="button" onClick={() => onOpenOrder(done.order_code)} className={btnCls}>
              Mở đơn {done.order_code}
            </button>
            {done.paid ? null : (
              <button type="button" onClick={() => void collect()} disabled={busy} className={btnPrimaryCls}>
                {busy ? "Đang thu…" : `Thu cả đơn · ${formatVnd(done.total)}`}
              </button>
            )}
          </>
        }
      >
        {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
        <SummaryBox>
          <p>
            Mã đơn <b className="font-mono">{done.order_code}</b> · {done.bookings.length} buổi
          </p>
          <p>
            Giá gốc {formatVnd(done.original_amount)}
            {done.discount_pct > 0 ? ` · giảm ${done.discount_pct}% (${formatVnd(done.discount_amount)})` : ""}
          </p>
          <p className="text-base font-bold">Phải thu {formatVnd(done.total)}</p>
          <p className={done.paid ? "font-medium text-primary" : "text-muted"}>{done.paid ? "Đã thanh toán (tiền mặt)" : "Chưa thanh toán. Thu cả đơn ngay hoặc sau ở Lịch sử giao dịch."}</p>
        </SummaryBox>
        <p className="text-xs text-muted">Mỗi buổi hiện trên lịch là một khối mang mã đơn. Chưa có hủy hay đổi buổi.</p>
      </Modal>
    );
  }

  // ---------------- Nhập + xem trước
  const sel = `${inputCls} h-10`;
  return (
    <Modal
      open
      onClose={onClose}
      size="wide"
      title="Đặt sân định kỳ"
      footer={
        <>
          <button type="button" onClick={onClose} className={btnCls}>
            Hủy
          </button>
          <button type="button" onClick={() => void runPreview()} disabled={busy} className={btnCls}>
            {busy && !preview ? "Đang tính…" : "Xem trước"}
          </button>
          <button type="button" onClick={() => void book()} disabled={busy || !preview || preview.conflicts_count > 0 || preview.count === 0} className={btnPrimaryCls}>
            {preview && preview.conflicts_count === 0 ? `Đặt ${preview.count} buổi` : "Đặt sân"}
          </button>
        </>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}

      <CustomerPicker state={customer} onChange={edit(setCustomer)} submitted={submitted} />

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor={ids.res} className="mb-1 block text-sm font-medium">
            Sân
          </label>
          <select id={ids.res} value={resource} onChange={(e) => edit(setResource)(e.target.value)} className={sel}>
            {resources.map((r) => (
              <option key={r.code} value={r.code}>
                {r.code} · {r.name}
              </option>
            ))}
          </select>
        </div>
        <fieldset>
          <legend className="mb-1 text-sm font-medium">Các thứ trong tuần</legend>
          <div className="flex flex-wrap gap-1.5">
            {DOW.map(([n, label]) => {
              const on = weekdays.includes(n);
              return (
                <button
                  key={n}
                  type="button"
                  aria-pressed={on}
                  onClick={() => edit(setWeekdays)(on ? weekdays.filter((x) => x !== n) : [...weekdays, n])}
                  className={`h-10 min-w-10 rounded-md border px-2 text-sm font-medium ${on ? "border-primary bg-primary text-white" : "border-border bg-background hover:bg-primary-softer"}`}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </fieldset>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor={ids.sh} className="mb-1 block text-sm font-medium">
              Giờ từ
            </label>
            <select id={ids.sh} value={startHour} onChange={(e) => edit(setStartHour)(Number(e.target.value))} className={sel}>
              {calendar.columns.map((h) => (
                <option key={h} value={h}>
                  {pad(h)}:00
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor={ids.eh} className="mb-1 block text-sm font-medium">
              Giờ đến
            </label>
            <select id={ids.eh} value={endHour} onChange={(e) => edit(setEndHour)(Number(e.target.value))} className={sel}>
              {calendar.columns.map((h) => (
                <option key={h + 1} value={h + 1}>
                  {pad(h + 1)}:00
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor={ids.from} className="mb-1 block text-sm font-medium">
              Từ ngày
            </label>
            <input id={ids.from} type="date" min={today} value={dateFrom} onChange={(e) => edit(setDateFrom)(e.target.value)} className={sel} />
          </div>
          <div>
            <label htmlFor={ids.to} className="mb-1 block text-sm font-medium">
              Đến ngày
            </label>
            <input id={ids.to} type="date" min={dateFrom} value={dateTo} onChange={(e) => edit(setDateTo)(e.target.value)} className={sel} />
          </div>
        </div>
        <div>
          <label htmlFor={ids.pct} className="mb-1 block text-sm font-medium">
            Giảm giá cả đơn (%)
          </label>
          <input id={ids.pct} inputMode="numeric" value={pct} onChange={(e) => edit(setPct)(e.target.value.replace(/[^\d]/g, "").slice(0, 3))} className={sel} />
        </div>
      </div>
      {submitted && formError ? <ErrorBanner>{formError}</ErrorBanner> : null}

      <Hint>Hệ thống sinh từng buổi, kiểm lịch theo từng ngày và đặt tất cả hoặc không đặt gì. Giá gốc theo bảng giá từng buổi, tối đa {MAX_DAYS} ngày và 60 buổi. Chưa có hủy hay đổi buổi: kiểm kỹ bảng xem trước.</Hint>

      {serverConflicts.length > 0 ? (
        <section aria-label="Buổi không đặt được">
          <ErrorBanner>
            Có {serverConflicts.length} buổi không đặt được, chưa tạo buổi nào. Đổi lịch rồi bấm Xem trước.
            <ul className="mt-1 list-disc pl-5">
              {serverConflicts.map((c) => (
                <li key={`${c.date}-${c.start}`}>
                  {dowName(c.date)} {formatDayMonthYear(c.date)} {hh(c.start)}: {c.reason_text ?? reasonText(c.reason)}
                </li>
              ))}
            </ul>
          </ErrorBanner>
        </section>
      ) : null}

      {preview ? (
        <section aria-label="Xem trước các buổi" className="space-y-2">
          <div className="max-h-72 overflow-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <caption className="sr-only">Danh sách {preview.count} buổi</caption>
              <thead className="sticky top-0 bg-background text-left text-xs text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">Ngày</th>
                  <th className="px-2 py-2 font-medium">Thứ</th>
                  <th className="px-2 py-2 font-medium">Giờ</th>
                  <th className="px-2 py-2 text-right font-medium">Giá gốc</th>
                  <th className="px-3 py-2 text-right font-medium">Sau giảm</th>
                </tr>
              </thead>
              <tbody>
                {preview.sessions.map((s) => (
                  <tr key={`${s.date}-${s.start_time}`} className={`border-t border-border ${s.ok ? "" : "bg-danger/10 text-danger"}`}>
                    <td className="px-3 py-1.5 tabular-nums">{formatDayMonthYear(s.date)}</td>
                    <td className="px-2 py-1.5">{dowName(s.date)}</td>
                    <td className="px-2 py-1.5 tabular-nums">
                      {hh(s.start_time)}–{hh(s.end_time)}
                    </td>
                    {s.ok ? (
                      <>
                        <td className="px-2 py-1.5 text-right tabular-nums">{s.price !== null ? formatVnd(s.price) : "—"}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums">{s.price_after_discount !== null ? formatVnd(s.price_after_discount) : "—"}</td>
                      </>
                    ) : (
                      <td colSpan={2} className="px-3 py-1.5 text-right font-medium">
                        {s.reason_text ?? reasonText(s.reason)}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <SummaryBox>
            <p>
              <b>{preview.count}</b> buổi · giá gốc {formatVnd(preview.original_amount)} · giảm {formatVnd(preview.discount_amount)}
            </p>
            <p className="text-base font-bold">Phải thu {formatVnd(preview.total)}</p>
            {preview.conflicts_count > 0 ? (
              <p role="alert" className="font-medium text-danger">
                Còn {preview.conflicts_count} buổi lỗi. Đổi lịch rồi xem trước lại mới đặt được.
              </p>
            ) : null}
          </SummaryBox>
        </section>
      ) : null}
    </Modal>
  );
}
