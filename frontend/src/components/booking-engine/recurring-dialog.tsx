"use client";

import { useEffect, useId, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatDayMonthYear, formatVnd } from "@/lib/format";
import { CustomerPicker, customerErrors, customerPayload, emptyCustomer, type CustomerState } from "./customer-picker";
import { authFailure } from "./booking-dialogs";
import { getRecurringPreview, sendCollectOrder, sendRecurring } from "./requests";
import type { Calendar, RecurringBody, RecurringConflict, RecurringPreview, RecurringResult } from "./types";
import { btnCls, btnPrimaryCls, ErrorBanner, Group, Hint, inputCls, SummaryBox } from "./ui";

// Đặt sân định kỳ (T-035, chỉ Admin), v2 (T-039): ba nhóm Khách · Lịch · Tiền, xem trước TỰ ĐỘNG khi đổi dữ liệu
// (debounce 400 ms, hủy lượt gọi cũ), điện thoại là màn toàn trang với nút Đặt dính đáy.

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
const DEBOUNCE_MS = 400;
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
  // Kết quả xem trước kèm khóa dữ liệu đã dùng; chỉ "tươi" khi khóa khớp dữ liệu đang nhập
  const [result, setResult] = useState<{ key: string; data: RecurringPreview } | null>(null);
  const [calculating, setCalculating] = useState(false);
  const [serverConflicts, setServerConflicts] = useState<RecurringConflict[]>([]);
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");
  const [done, setDone] = useState<(RecurringResult & { paid: boolean }) | null>(null);

  const edit = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setServerConflicts([]);
    setBanner("");
  };

  const pctNum = pct.trim() === "" ? NaN : Number(pct);
  const cErr = customerErrors(customer);
  const formError =
    Object.keys(cErr).length > 0 ? "Chọn khách (hội viên hoặc hồ sơ tạm)" :
    !resource ? "Chọn sân" :
    weekdays.length === 0 ? "Chọn ít nhất một thứ trong tuần" :
    endHour <= startHour ? "Giờ kết thúc phải sau giờ bắt đầu" :
    !dateFrom || !dateTo || dateTo < dateFrom ? "Khoảng ngày không hợp lệ" :
    dateFrom < today ? "Từ ngày không được trước hôm nay" :
    dateTo > addDays(dateFrom, MAX_DAYS - 1) ? `Khoảng ngày tối đa ${MAX_DAYS} ngày` :
    !Number.isInteger(pctNum) || pctNum < 0 || pctNum > 100 ? "% giảm là số nguyên từ 0 đến 100" : "";

  const payload: RecurringBody | null = (() => {
    const c = customerPayload(customer);
    if (!c || formError) return null;
    return { customer: c, resource_code: resource, weekdays: [...weekdays].sort(), start_hour: startHour, end_hour: endHour, date_from: dateFrom, date_to: dateTo, discount_pct: pctNum };
  })();
  const key = payload ? JSON.stringify(payload) : "";

  // Xem trước tự động: đổi dữ liệu → đợi 400 ms → gọi; đổi tiếp thì hủy lượt cũ (kết quả cũ không được áp dụng)
  useEffect(() => {
    if (!key) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- thiếu dữ liệu: không gọi API
      setCalculating(false);
      return;
    }
    const ctl = new AbortController();
     
    setCalculating(true);
    const timer = setTimeout(async () => {
      const res = await getRecurringPreview(JSON.parse(key) as RecurringBody, ctl.signal);
      if (ctl.signal.aborted) return;
      setCalculating(false);
      if (res.ok) {
        setResult({ key, data: res.data });
        setBanner("");
      } else if (!authFailure(res.error)) setBanner(errorText(res.error));
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      ctl.abort();
    };
  }, [key]);

  const preview = result && result.key === key ? result.data : null;
  const canBook = Boolean(payload && preview && !calculating && !busy && preview.conflicts_count === 0 && preview.count > 0);

  async function book() {
    if (!payload || !canBook) return;
    setBusy(true);
    setBanner("");
    try {
      const res = await write((k) => sendRecurring(k, payload));
      if (!res.ok) {
        const e = res.error;
        if (authFailure(e)) return;
        if (e.code === "E-BOOK-5" && Array.isArray(e.extra.conflicts)) {
          // Có buổi không đặt được (kể cả tranh chấp đồng thời): không tạo gì; hiện danh sách buổi lỗi
          setServerConflicts(e.extra.conflicts as RecurringConflict[]);
          setResult(null);
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
      const res = await write((k) => sendCollectOrder(k, done.order_code));
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
          <p className={done.paid ? "font-medium text-primary" : "text-muted"}>{done.paid ? "Đã thanh toán (tiền mặt)" : "Chưa thanh toán. Thu cả đơn ngay hoặc sau ở màn Đơn định kỳ."}</p>
        </SummaryBox>
        <p className="text-xs text-muted">Mỗi buổi hiện trên lịch là một khối mang mã đơn. Chưa có hủy hay đổi buổi.</p>
      </Modal>
    );
  }

  // ---------------- Nhập + xem trước tự động
  const sel = `${inputCls} h-10`;
  return (
    <Modal
      open
      full
      onClose={onClose}
      size="wide"
      title="Đặt sân định kỳ"
      footer={
        <>
          <button type="button" onClick={onClose} className={`${btnCls} max-md:h-12`}>
            Hủy
          </button>
          <button type="button" onClick={() => void book()} disabled={!canBook} className={`${btnPrimaryCls} max-md:h-12 max-md:flex-1`}>
            {busy ? "Đang đặt…" : canBook && preview ? `Đặt ${preview.count} buổi · ${formatVnd(preview.total)}` : "Đặt sân"}
          </button>
        </>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}

      <Group title="Khách">
        <CustomerPicker state={customer} onChange={edit(setCustomer)} submitted={false} />
      </Group>

      <Group title="Lịch">
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
        </div>
        <fieldset className="mt-3">
          <legend className="mb-1 text-sm font-medium">Các thứ trong tuần</legend>
          <div className="grid grid-cols-7 gap-1.5">
            {DOW.map(([n, label]) => {
              const on = weekdays.includes(n);
              return (
                <button
                  key={n}
                  type="button"
                  aria-pressed={on}
                  onClick={() => edit(setWeekdays)(on ? weekdays.filter((x) => x !== n) : [...weekdays, n])}
                  className={`h-10 rounded-md border text-sm font-medium ${on ? "border-primary bg-primary text-white" : "border-border bg-background hover:bg-primary-softer"}`}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </fieldset>
        <div className="mt-3 grid grid-cols-2 gap-3">
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
      </Group>

      <Group title="Tiền">
        <div className="grid gap-3 sm:grid-cols-[11rem_1fr] sm:items-start">
          <div>
            <label htmlFor={ids.pct} className="mb-1 block text-sm font-medium">
              Giảm giá cả đơn (%)
            </label>
            <input id={ids.pct} inputMode="numeric" value={pct} onChange={(e) => edit(setPct)(e.target.value.replace(/[^\d]/g, "").slice(0, 3))} className={sel} />
          </div>
          <SummaryBox>
            {!payload ? (
              <p className="text-muted">Nhập {formError.toLowerCase()} để xem trước các buổi và tiền.</p>
            ) : calculating || !preview ? (
              <p className="text-muted" role="status">
                Đang tính…
              </p>
            ) : (
              <>
                <p>
                  <b>{preview.count}</b> buổi · giá gốc {formatVnd(preview.original_amount)} · giảm {formatVnd(preview.discount_amount)}
                </p>
                <p className="text-base font-bold">Phải thu {formatVnd(preview.total)}</p>
                {preview.conflicts_count > 0 ? (
                  <p role="alert" className="font-medium text-danger">
                    Còn {preview.conflicts_count} buổi lỗi. Đổi lịch mới đặt được.
                  </p>
                ) : null}
              </>
            )}
          </SummaryBox>
        </div>
      </Group>

      <Hint>Hệ thống sinh từng buổi, kiểm lịch theo từng ngày và đặt tất cả hoặc không đặt gì. Giá gốc theo bảng giá từng buổi, tối đa {MAX_DAYS} ngày và 60 buổi. Chưa có hủy hay đổi buổi: kiểm kỹ bảng xem trước.</Hint>

      {serverConflicts.length > 0 ? (
        <section aria-label="Buổi không đặt được">
          <ErrorBanner>
            Có {serverConflicts.length} buổi không đặt được, chưa tạo buổi nào. Đổi lịch, bảng xem trước sẽ tự cập nhật.
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
        <section aria-label="Các buổi sẽ đặt" className={`space-y-2 ${calculating ? "opacity-60" : ""}`} aria-busy={calculating}>
          {/* Từ md: bảng; điện thoại: danh sách thẻ */}
          <div className="hidden max-h-72 overflow-auto rounded-lg border border-border md:block">
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
          <ul className="space-y-2 md:hidden">
            {preview.sessions.map((s) => (
              <li key={`${s.date}-${s.start_time}`} className={`rounded-lg border p-3 text-sm ${s.ok ? "border-border" : "border-danger/40 bg-danger/10 text-danger"}`}>
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-medium tabular-nums">
                    {dowName(s.date)} {formatDayMonthYear(s.date)}
                  </span>
                  <span className="tabular-nums">
                    {hh(s.start_time)}–{hh(s.end_time)}
                  </span>
                </div>
                {s.ok ? (
                  <p className="mt-1 flex justify-between gap-3 tabular-nums">
                    <span className="text-muted">Giá gốc {s.price !== null ? formatVnd(s.price) : "—"}</span>
                    <b>{s.price_after_discount !== null ? formatVnd(s.price_after_discount) : "—"}</b>
                  </p>
                ) : (
                  <p className="mt-1 font-medium">{s.reason_text ?? reasonText(s.reason)}</p>
                )}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </Modal>
  );
}
