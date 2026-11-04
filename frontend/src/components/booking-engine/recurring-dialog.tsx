"use client";

import { useEffect, useId, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatDayMonthYear, formatVnd } from "@/lib/format";
import { CustomerPicker, customerErrors, customerPayload, emptyCustomer, type CustomerState } from "./customer-picker";
import { authFailure } from "./booking-dialogs";
import { getRecurringPreview, sendCollectOrder, sendRecurring } from "./requests";
import type { Calendar, RecurringBody, RecurringConflict, RecurringPreview, RecurringResult, RecurringSessionIn, RecurringSuggestion } from "./types";
import { btnCls, btnPrimaryCls, ErrorBanner, Group, Hint, inputCls, SummaryBox } from "./ui";

// Đặt sân định kỳ (T-035, chỉ Admin), v2 (T-039), linh động (T-043): gợi ý buổi lỗi, sửa / bỏ từng buổi, xem trước gọn.
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

/** Chỉnh sửa của một buổi so với lịch chung. */
type Tweak = { resource_code?: string; start_hour?: number; end_hour?: number; removed?: boolean };

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
  // Chỉnh từng buổi, khóa theo ngày (mỗi ngày tối đa một buổi): đổi sân / giờ hoặc bỏ buổi (T-043 AC3)
  const [tweaks, setTweaks] = useState<Record<string, Tweak>>({});
  const [editingDay, setEditingDay] = useState<string | null>(null);
  const [showOk, setShowOk] = useState(false);
  const [tick, setTick] = useState(0);
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");
  const [done, setDone] = useState<(RecurringResult & { paid: boolean }) | null>(null);

  const edit = <T,>(set: (v: T) => void, resetTweaks = false) => (v: T) => {
    set(v);
    setServerConflicts([]);
    setBanner("");
    if (resetTweaks) {
      setTweaks({});
      setEditingDay(null);
    }
  };

  // Các buổi sinh từ lịch chung (theo thứ trong tuần), rồi áp chỉnh sửa / lượt bỏ của từng buổi
  const base: RecurringSessionIn[] = (() => {
    if (!dateFrom || !dateTo || dateTo < dateFrom || dateTo > addDays(dateFrom, MAX_DAYS - 1) || weekdays.length === 0) return [];
    const out: RecurringSessionIn[] = [];
    for (let d = dateFrom; d <= dateTo; d = addDays(d, 1)) if (weekdays.includes(isoDow(d))) out.push({ date: d, resource_code: resource, start_hour: startHour, end_hour: endHour });
    return out;
  })();
  const effective = base.filter((b) => !tweaks[b.date]?.removed).map((b) => ({ ...b, ...tweaks[b.date], removed: undefined })) as RecurringSessionIn[];
  const removedDays = base.filter((b) => tweaks[b.date]?.removed);

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
    !Number.isInteger(pctNum) || pctNum < 0 || pctNum > 100 ? "% giảm là số nguyên từ 0 đến 100" :
    base.length > 0 && effective.length === 0 ? "Đã bỏ hết các buổi" : "";

  const payload: RecurringBody | null = (() => {
    const c = customerPayload(customer);
    if (!c || formError) return null;
    return { customer: c, resource_code: resource, weekdays: [...weekdays].sort(), start_hour: startHour, end_hour: endHour, date_from: dateFrom, date_to: dateTo, discount_pct: pctNum, sessions: effective };
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
  }, [key, tick]);

  const preview = result && result.key === key ? result.data : null;
  const canBook = Boolean(payload && preview && !calculating && !busy && preview.conflicts_count === 0 && preview.count > 0);

  const setTweak = (day: string, t: Tweak | null) =>
    setTweaks((cur) => {
      const next = { ...cur };
      if (t) next[day] = { ...cur[day], ...t };
      else delete next[day];
      return next;
    });
  /** Áp một gợi ý cho buổi ngày `day`: đổi sân + giờ (T-043 AC2). */
  const applySuggestion = (day: string, sg: RecurringSuggestion) => setTweak(day, { resource_code: sg.resource_code, start_hour: sg.start_hour, end_hour: sg.end_hour });

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
          setTick((n) => n + 1); // tính lại ngay để thấy buổi lỗi + gợi ý mới
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
            <select id={ids.res} value={resource} onChange={(e) => edit(setResource, true)(e.target.value)} className={sel}>
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
              <select id={ids.sh} value={startHour} onChange={(e) => edit(setStartHour, true)(Number(e.target.value))} className={sel}>
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
              <select id={ids.eh} value={endHour} onChange={(e) => edit(setEndHour, true)(Number(e.target.value))} className={sel}>
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
                  onClick={() => edit(setWeekdays, true)(on ? weekdays.filter((x) => x !== n) : [...weekdays, n])}
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
            <input id={ids.from} type="date" min={today} value={dateFrom} onChange={(e) => edit(setDateFrom, true)(e.target.value)} className={sel} />
          </div>
          <div>
            <label htmlFor={ids.to} className="mb-1 block text-sm font-medium">
              Đến ngày
            </label>
            <input id={ids.to} type="date" min={dateFrom} value={dateTo} onChange={(e) => edit(setDateTo, true)(e.target.value)} className={sel} />
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
                  <b>{preview.count}</b> buổi · gốc {formatVnd(preview.original_amount)} · giảm {formatVnd(preview.discount_amount)} · <b className="text-base">phải thu {formatVnd(preview.total)}</b>
                </p>
                {preview.conflicts_count > 0 ? (
                  <p role="alert" className="font-medium text-danger">
                    Còn {preview.conflicts_count} buổi lỗi. Dùng gợi ý, sửa hoặc bỏ buổi để tiếp tục.
                  </p>
                ) : null}
              </>
            )}
          </SummaryBox>
        </div>
      </Group>

      <Hint>Hệ thống sinh từng buổi, kiểm lịch theo từng ngày và đặt tất cả hoặc không đặt gì. Giá gốc theo bảng giá từng buổi, tối đa {MAX_DAYS} ngày và 60 buổi. Buổi lỗi có thể dùng gợi ý, sửa giờ / sân hoặc bỏ riêng. Đặt xong chưa có hủy hay đổi buổi.</Hint>

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

      <SessionsPanel
        preview={preview}
        calculating={calculating}
        resources={resources}
        columns={calendar.columns}
        tweaks={tweaks}
        removedDays={removedDays}
        editingDay={editingDay}
        setEditingDay={setEditingDay}
        setTweak={setTweak}
        applySuggestion={applySuggestion}
        showOk={showOk}
        setShowOk={setShowOk}
      />
    </Modal>
  );
}

type PanelProps = {
  preview: RecurringPreview | null;
  calculating: boolean;
  resources: Calendar["resources"];
  columns: number[];
  tweaks: Record<string, Tweak>;
  removedDays: RecurringSessionIn[];
  editingDay: string | null;
  setEditingDay: (d: string | null) => void;
  setTweak: (day: string, t: Tweak | null) => void;
  applySuggestion: (day: string, sg: RecurringSuggestion) => void;
  showOk: boolean;
  setShowOk: (v: boolean) => void;
};

const KIND_LABEL: Record<RecurringSuggestion["kind"], string> = { shift: "Lệch giờ", court: "Sân khác" };

/** Xem trước gọn (T-043 AC4): chỉ buổi lỗi + dòng gộp "✓ n buổi hợp lệ" (bấm để mở), buổi đã bỏ có Hoàn tác. */
function SessionsPanel({ preview, calculating, resources, columns, tweaks, removedDays, editingDay, setEditingDay, setTweak, applySuggestion, showOk, setShowOk }: PanelProps) {
  if (!preview && removedDays.length === 0) return null;
  const sessions = preview?.sessions ?? [];
  const bad = sessions.filter((s) => !s.ok);
  const good = sessions.filter((s) => s.ok);
  const nameOf = (code?: string) => resources.find((r) => r.code === code)?.name ?? code ?? "";

  // "Áp cho mọi buổi {thứ} lỗi": nhóm các buổi lỗi cùng thứ có cùng kiểu gợi ý (≥ 2 buổi)
  const bulk = new Map<string, { dow: string; kind: RecurringSuggestion["kind"]; days: { date: string; sg: RecurringSuggestion }[] }>();
  for (const s of bad) {
    for (const sg of s.suggestions ?? []) {
      const k = `${isoDow(s.date)}|${sg.kind}`;
      const g = bulk.get(k) ?? { dow: dowName(s.date), kind: sg.kind, days: [] };
      g.days.push({ date: s.date, sg });
      bulk.set(k, g);
    }
  }
  const bulkList = [...bulk.values()].filter((g) => g.days.length >= 2);
  const smallBtn = "min-h-10 rounded-md border border-border px-3 text-sm hover:bg-primary-softer focus-ring";

  const row = (s: (typeof sessions)[number], bad: boolean) => {
    const tw = tweaks[s.date];
    const code = s.resource_code ?? tw?.resource_code;
    const editing = editingDay === s.date;
    return (
      <li key={s.date} className={`rounded-lg border p-3 text-sm ${bad ? "border-danger/40 bg-danger/10" : "border-border"}`}>
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <span className="font-medium tabular-nums">
            {dowName(s.date)} {formatDayMonthYear(s.date)} · {hh(s.start_time)}–{hh(s.end_time)}
            {code ? <span className="font-normal text-muted"> · {nameOf(code)}</span> : null}
          </span>
          <span className="flex items-center gap-2">
            {tw ? <span className="rounded-full bg-primary-softer px-2 py-0.5 text-xs font-medium text-primary">Đã chỉnh</span> : null}
            {bad ? <b className="text-danger">{s.reason_text ?? reasonText(s.reason)}</b> : <span className="tabular-nums">{s.price_after_discount !== null ? formatVnd(s.price_after_discount) : "—"}</span>}
          </span>
        </div>

        {bad && (s.suggestions?.length ?? 0) > 0 ? (
          <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label={`Gợi ý cho ${dowName(s.date)} ${formatDayMonthYear(s.date)}`}>
            {s.suggestions!.map((sg) => (
              <button key={`${sg.kind}-${sg.resource_code}-${sg.start_hour}`} type="button" onClick={() => applySuggestion(s.date, sg)} className={`${smallBtn} border-primary text-primary`}>
                Dùng gợi ý · {KIND_LABEL[sg.kind]}: {sg.kind === "court" ? `${sg.resource_name} ` : ""}
                {pad(sg.start_hour)}–{pad(sg.end_hour)}h · {formatVnd(sg.price)}
              </button>
            ))}
          </div>
        ) : null}

        <div className="mt-2 flex flex-wrap gap-2">
          <button type="button" onClick={() => setEditingDay(editing ? null : s.date)} aria-expanded={editing} className={smallBtn}>
            {editing ? "Xong" : "Sửa giờ / sân"}
          </button>
          <button type="button" onClick={() => setTweak(s.date, { removed: true })} className={smallBtn}>
            Bỏ buổi
          </button>
          {tw ? (
            <button type="button" onClick={() => setTweak(s.date, null)} className={smallBtn}>
              Hoàn tác
            </button>
          ) : null}
        </div>

        {editing ? (
          <div className="mt-2 grid grid-cols-3 gap-2">
            <label className="text-xs text-muted">
              Sân
              <select value={code ?? ""} onChange={(e) => setTweak(s.date, { resource_code: e.target.value })} className={`${inputCls} mt-0.5 h-10`}>
                {resources.map((r) => (
                  <option key={r.code} value={r.code}>
                    {r.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-muted">
              Từ
              <select value={Number(s.start_time.slice(0, 2))} onChange={(e) => setTweak(s.date, { start_hour: Number(e.target.value), end_hour: Math.max(Number(e.target.value) + 1, tw?.end_hour ?? Number(s.end_time.slice(0, 2))) })} className={`${inputCls} mt-0.5 h-10`}>
                {columns.map((h) => (
                  <option key={h} value={h}>
                    {pad(h)}:00
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-muted">
              Đến
              <select value={Number(s.end_time.slice(0, 2))} onChange={(e) => setTweak(s.date, { end_hour: Number(e.target.value) })} className={`${inputCls} mt-0.5 h-10`}>
                {columns.filter((h) => h + 1 > Number(s.start_time.slice(0, 2))).map((h) => (
                  <option key={h + 1} value={h + 1}>
                    {pad(h + 1)}:00
                  </option>
                ))}
              </select>
            </label>
          </div>
        ) : null}
      </li>
    );
  };

  return (
    <section aria-label="Các buổi cần xử lý" className={`space-y-2 ${calculating ? "opacity-60" : ""}`} aria-busy={calculating}>
      {bulkList.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {bulkList.map((g) => (
            <button key={`${g.dow}-${g.kind}`} type="button" onClick={() => g.days.forEach((d) => applySuggestion(d.date, d.sg))} className={`${smallBtn} border-primary text-primary`}>
              Áp “{KIND_LABEL[g.kind].toLowerCase()}” cho mọi buổi {g.dow} lỗi ({g.days.length})
            </button>
          ))}
        </div>
      ) : null}

      {bad.length > 0 ? <ul className="space-y-2">{bad.map((s) => row(s, true))}</ul> : null}

      {removedDays.length > 0 ? (
        <ul className="space-y-1" aria-label="Buổi đã bỏ">
          {removedDays.map((r) => (
            <li key={r.date} className="flex items-center justify-between gap-3 rounded-lg border border-dashed border-border px-3 py-2 text-sm text-muted">
              <span className="tabular-nums line-through">
                {dowName(r.date)} {formatDayMonthYear(r.date)}
              </span>
              <button type="button" onClick={() => setTweak(r.date, null)} className="min-h-9 rounded-md px-2 text-primary hover:underline focus-ring">
                Hoàn tác
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {good.length > 0 ? (
        <div>
          <button type="button" onClick={() => setShowOk(!showOk)} aria-expanded={showOk} className="flex min-h-11 w-full items-center justify-between gap-2 rounded-lg border border-border bg-background px-3 text-left text-sm font-medium focus-ring">
            <span>✓ {good.length} buổi hợp lệ</span>
            <span aria-hidden className="text-muted">
              {showOk ? "Thu gọn ▴" : "Xem ▾"}
            </span>
          </button>
          {showOk ? <ul className="mt-2 space-y-2">{good.map((s) => row(s, false))}</ul> : null}
        </div>
      ) : null}
    </section>
  );
}
