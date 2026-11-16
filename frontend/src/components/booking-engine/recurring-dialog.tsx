"use client";

import { useCallback, useEffect, useId, useState } from "react";
import { Dropdown } from "@/components/ui/dropdown";
import { Field } from "@/components/ui/field";
import { Modal } from "@/components/ui/modal";
import { cn } from "@/lib/cn";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { addDaysIso, formatDayMonthYear, formatVnd, hhmm } from "@/lib/format";
import { CustomerPicker, customerErrors, customerPayload, emptyCustomer, type CustomerState } from "./customer-picker";
import { authFailure } from "./booking-dialogs";
import { getRecurringPreview, sendCollectOrder, sendRecurring } from "./requests";
import { RecurringDone } from "./recurring-done";
import { PriceFooter } from "./recurring-price";
import { SessionsPanel } from "./recurring-sessions";
import { DEBOUNCE_MS, DOW, dowName, hourOptions, isoDow, MAX_DAYS, reasonText, type Tweak } from "./recurring-utils";
import type { Calendar, RecurringBody, RecurringConflict, RecurringPreviewBody, RecurringPreview, RecurringResult, RecurringSessionIn, RecurringSuggestion } from "./types";
import { btnCls, btnPrimaryCls, btnRowCls, dropdownCls, ErrorBanner, Group, inputCls, raisedFooterCls } from "./ui";

// Đặt sân định kỳ (T-035, chỉ Admin), v2 (T-039), linh động (T-043): gợi ý buổi lỗi, sửa / bỏ từng buổi, xem trước gọn.
// Đặt sân định kỳ (T-035, chỉ Admin), v2 (T-039): ba nhóm Khách · Lịch · Tiền, xem trước TỰ ĐỘNG khi đổi dữ liệu
// (debounce 400 ms, hủy lượt gọi cũ), điện thoại là màn toàn trang với nút Đặt dính đáy.

type Props = {
  calendar: Calendar;
  today: string;
  onClose: () => void;
  /** Đã đặt (hoặc đã thu tiền): cha tải lại lịch và tô sáng đơn. */
  onChanged: (orderCode: string) => void;
  onOpenOrder: (orderCode: string) => void;
};

export function RecurringDialog({ calendar, today, onClose, onChanged, onOpenOrder }: Props) {
  const ids = { res: useId(), from: useId(), to: useId(), sh: useId(), pct: useId() };
  const resources = calendar.resources.filter((r) => r.is_active);
  const first = calendar.columns[0] ?? 6;
  const last = (calendar.columns[calendar.columns.length - 1] ?? 21) + 1;

  const [customer, setCustomer] = useState<CustomerState>(emptyCustomer);
  const [resource, setResource] = useState(resources[0]?.code ?? "");
  const [weekdays, setWeekdays] = useState<number[]>([]);
  const [startHour, setStartHour] = useState(Math.min(first + 12, last - 1));
  const [endHour, setEndHour] = useState(Math.min(first + 14, last));
  const [dateFrom, setDateFrom] = useState(today);
  const [dateTo, setDateTo] = useState(addDaysIso(today, 30));
  const [pct, setPct] = useState("0");
  // Kết quả xem trước kèm khóa dữ liệu đã dùng; chỉ "tươi" khi khóa khớp dữ liệu đang nhập
  const [result, setResult] = useState<{ key: string; data: RecurringPreview } | null>(null);
  const [calculating, setCalculating] = useState(false);
  const [serverConflicts, setServerConflicts] = useState<RecurringConflict[]>([]);
  // Chỉnh từng buổi, khóa theo ngày (mỗi ngày tối đa một buổi): đổi sân / giờ hoặc bỏ buổi (T-043 AC3)
  const [tweaks, setTweaks] = useState<Record<string, Tweak>>({});
  const [editingDay, setEditingDay] = useState<string | null>(null);
  // Nhóm "✓ n buổi hợp lệ": thu gọn mặc định, bấm mới bung (cấu trúc gốc của dev)
  const [showOk, setShowOk] = useState(false);
  const [tick, setTick] = useState(0);
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");
  const [done, setDone] = useState<(RecurringResult & { paid: boolean }) | null>(null);

  // Giờ mở cửa của sân đang chọn: cột lịch trừ giờ không bán (off_hours); đóng cửa = giờ mở cuối + 1
  const hoursOf = (code: string) => {
    const off = resources.find((r) => r.code === code)?.off_hours ?? [];
    const cols = calendar.columns.filter((h) => !off.includes(h));
    return cols.length ? cols : calendar.columns;
  };
  const openCols = hoursOf(resource);
  const close = (openCols[openCols.length - 1] ?? last - 1) + 1;
  /** Kẹp khung giờ vào giờ mở cửa: bắt đầu trong [mở, đóng − 1], kết thúc trong [bắt đầu + 1, đóng]. */
  const clampSlot = (start: number, end: number, cols: number[]) => {
    const open = cols[0] ?? first;
    const shut = (cols[cols.length - 1] ?? last - 1) + 1;
    const s0 = Math.min(Math.max(start, open), shut - 1);
    return [s0, Math.min(Math.max(end, s0 + 1), shut)] as const;
  };

  const edit = <T,>(set: (v: T) => void, resetTweaks = false) => (v: T) => {
    set(v);
    setServerConflicts([]);
    setBanner("");
    if (resetTweaks) {
      setTweaks({});
      setEditingDay(null);
    }
  };

  /** Đổi giờ bắt đầu ⇒ giữ độ dài cũ, kẹp về giờ đóng cửa (tối thiểu 1 tiếng). */
  const changeStart = (h: number) => {
    const [s0, e0] = clampSlot(h, h + (endHour - startHour), openCols);
    edit(setStartHour, true)(s0);
    setEndHour(e0);
  };
  /** Đổi sân ⇒ kẹp cả hai giờ vào khung mở cửa của sân mới. */
  const changeResource = (code: string) => {
    const [s0, e0] = clampSlot(startHour, endHour, hoursOf(code));
    edit(setResource, true)(code);
    setStartHour(s0);
    setEndHour(e0);
  };

  // Các buổi sinh từ lịch chung (theo thứ trong tuần), rồi áp chỉnh sửa / lượt bỏ của từng buổi
  const base: RecurringSessionIn[] = (() => {
    if (!dateFrom || !dateTo || dateTo < dateFrom || dateTo > addDaysIso(dateFrom, MAX_DAYS - 1) || weekdays.length === 0) return [];
    const out: RecurringSessionIn[] = [];
    for (let d = dateFrom; d <= dateTo; d = addDaysIso(d, 1)) if (weekdays.includes(isoDow(d))) out.push({ date: d, resource_code: resource, start_hour: startHour, end_hour: endHour });
    return out;
  })();
  const effective = base.filter((b) => !tweaks[b.date]?.removed).map((b) => ({ ...b, ...tweaks[b.date], removed: undefined })) as RecurringSessionIn[];
  const removedDays = base.filter((b) => tweaks[b.date]?.removed);

  const pctNum = pct.trim() === "" ? NaN : Number(pct);
  const cErr = customerErrors(customer);
  // Lỗi lịch (không gồm khách): đủ ⇒ xem trước danh sách ngày NGAY khi chọn thứ, chưa cần chọn khách
  const scheduleError =
    !resource ? "Chọn sân" :
    weekdays.length === 0 ? "Chọn ít nhất một thứ trong tuần" :
    endHour <= startHour ? "Giờ kết thúc phải sau giờ bắt đầu" :
    !dateFrom || !dateTo || dateTo < dateFrom ? "Khoảng ngày không hợp lệ" :
    dateFrom < today ? "Từ ngày không được trước hôm nay" :
    dateTo > addDaysIso(dateFrom, MAX_DAYS - 1) ? `Khoảng ngày tối đa ${MAX_DAYS} ngày` :
    !Number.isInteger(pctNum) || pctNum < 0 || pctNum > 100 ? "% giảm là số nguyên từ 0 đến 100" :
    base.length > 0 && effective.length === 0 ? "Đã bỏ hết các buổi" : "";
  const customerError = Object.keys(cErr).length > 0 ? "Chọn khách (hội viên hoặc hồ sơ tạm)" : "";

  // Xem trước: khách không bắt buộc (có thì gửi kèm); đặt: cần đủ khách
  const previewBody: RecurringPreviewBody | null = scheduleError
    ? null
    : { resource_code: resource, weekdays: [...weekdays].sort(), start_hour: startHour, end_hour: endHour, date_from: dateFrom, date_to: dateTo, discount_pct: pctNum, sessions: effective, customer: customerPayload(customer) ?? undefined };
  const payload: RecurringBody | null = (() => {
    const c = customerPayload(customer);
    if (!c || customerError || !previewBody) return null;
    return { ...previewBody, customer: c };
  })();
  const key = previewBody ? JSON.stringify(previewBody) : "";

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
      const res = await getRecurringPreview(JSON.parse(key) as RecurringPreviewBody, ctl.signal);
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

  /** Kiểm một buổi đang sửa: xem trước đúng buổi đó với cùng khách và % giảm, chưa áp vào đơn. */
  const checkSession = useCallback(
    async (session: RecurringSessionIn, signal: AbortSignal) => {
      const res = await getRecurringPreview({ ...(JSON.parse(key) as RecurringPreviewBody), sessions: [session] }, signal);
      if (!res.ok && !signal.aborted) authFailure(res.error);
      return res;
    },
    [key],
  );

  const preview = result && result.key === key ? result.data : null;
  const okSessions = preview?.sessions.filter((x) => x.ok) ?? [];
  // Tiền gốc / tổng của BE tính cả buổi lỗi ⇒ còn lỗi thì cộng từ buổi hợp lệ (giá BE từng buổi, đã giảm);
  // hết lỗi thì dùng đúng số tổng của BE (là số sẽ thu khi đặt)
  const money = !preview
    ? null
    : preview.conflicts_count === 0
      ? { original: preview.original_amount, discount: preview.discount_amount, total: preview.total }
      : (() => {
          const original = okSessions.reduce((n, x) => n + (x.price ?? 0), 0);
          const total = okSessions.reduce((n, x) => n + (x.price_after_discount ?? 0), 0);
          return { original, discount: original - total, total };
        })();
  const canBook = Boolean(payload && preview && !calculating && !busy && preview.conflicts_count === 0 && preview.count > 0);
  const lockReason = busy
    ? ""
    : scheduleError || customerError
      ? scheduleError || "Chưa chọn khách"
      : !preview || calculating
        ? "Đang kiểm lịch…"
        : preview.conflicts_count > 0
          ? `Còn ${preview.conflicts_count} buổi lỗi`
          : "";

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
  if (done) return <RecurringDone done={done} busy={busy} banner={banner} onClose={onClose} onOpenOrder={onOpenOrder} onCollect={() => void collect()} />;

  // ---------------- Nhập + xem trước tự động. Điện thoại: màn toàn trang, nút Đặt dính đáy (Modal `full`)
  return (
    <Modal
      open
      full
      onClose={onClose}
      size="wide"
      title="Đặt sân định kỳ"
      footerClassName={raisedFooterCls}
      // Chân dính đáy, lưới 2 cột × 2 hàng (từ sm): [khối giá ≤ 24rem, co lại khi hộp hẹp | nút Hủy / Đặt (căn đáy theo dòng Tổng)]
      // [Chưa tính n buổi lỗi]. Lý do khóa nút Đặt chỉ ở tooltip (người dùng bỏ dòng chữ). Điện thoại: giá → ghi chú → nút.
      footer={
        <div className="grid w-full gap-x-6 gap-y-1.5 sm:grid-cols-[minmax(0,24rem)_1fr] sm:items-end">
          {preview && money && okSessions.length > 0 ? (
            <PriceFooter
              lines={okSessions.map((x) => ({ price: x.price ?? 0, time: `${hhmm(x.start_time)}–${hhmm(x.end_time)}` }))}
              originalAmount={money.original}
              discountPct={preview.discount_pct}
              discountAmount={money.discount}
              total={money.total}
            />
          ) : (
            <span className="hidden sm:block" />
          )}
          {preview && preview.conflicts_count > 0 && okSessions.length > 0 ? (
            <p className="text-xs text-danger sm:col-start-1 sm:row-start-2">Chưa tính {preview.conflicts_count} buổi lỗi.</p>
          ) : null}
          {/* Hai nút rộng bằng nhau: điện thoại chia đôi bề ngang; từ sm mỗi nút 7rem, căn phải */}
          <div className={cn(btnRowCls, "grid-cols-2 sm:col-start-2 sm:row-start-1 sm:ml-auto sm:w-auto sm:grid-cols-[7rem_7rem]")}>
            <button type="button" onClick={onClose} className={btnCls}>
              Hủy
            </button>
            <button type="button" onClick={() => void book()} disabled={!canBook} title={lockReason || undefined} className={cn(btnPrimaryCls, "whitespace-nowrap")}>
              {busy ? "Đang đặt…" : canBook && preview ? `Đặt ${preview.count} buổi` : "Đặt sân"}
            </button>
          </div>
        </div>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}

      <Group title="1. Khách">
        <CustomerPicker state={customer} onChange={edit(setCustomer)} submitted={false} />
      </Group>

      {/* Lịch: sân, giờ, khoảng ngày, thứ; chọn thứ xong hiện NGAY danh sách ngày sẽ đặt (Trống / Đã có người đặt…) */}
      <Group title="2. Lịch">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="col-span-2">
            <Field label="Sân" htmlFor={ids.res}>
              <Dropdown
                id={ids.res}
                value={resource}
                onChange={changeResource}
                options={resources.map((r) => ({ value: r.code, label: `${r.code} · ${r.name}` }))}
                className={dropdownCls}
              />
            </Field>
          </div>
          {/* Khung giờ: một nhóm [từ ▾] → [đến ▾] · n giờ; giờ đến chỉ có giờ > giờ từ, trong giờ mở cửa của sân */}
          <div className="col-span-2">
            <Field label="Khung giờ" htmlFor={ids.sh}>
              <div className="flex items-center gap-1.5">
                <Dropdown id={ids.sh} aria-label="Giờ bắt đầu" value={String(startHour)} onChange={(v) => changeStart(Number(v))} options={hourOptions(openCols.filter((h) => h < close))} className={cn(dropdownCls, "min-w-0 flex-1 [&>button]:tabular-nums")} />
                <span aria-hidden className="text-muted">→</span>
                <Dropdown aria-label="Giờ kết thúc" value={String(endHour)} onChange={(v) => edit(setEndHour, true)(Number(v))} options={hourOptions(openCols.filter((h) => h + 1 > startHour), true)} className={cn(dropdownCls, "min-w-0 flex-1 [&>button]:tabular-nums")} />
                <span className="shrink-0 text-sm text-muted tabular-nums">· {endHour - startHour} giờ</span>
              </div>
            </Field>
          </div>
        </div>
        {/* Từ ngày | Đến ngày | các thứ (nút tròn) cùng một hàng, căn đáy; hẹp ⇒ thứ xuống hàng dưới, dàn đều bề ngang */}
        <div className="mt-3 flex flex-wrap items-end gap-x-4 gap-y-3">
          <div className="grid w-full grid-cols-2 gap-3 sm:w-auto sm:min-w-72 sm:flex-1">
            <Field label="Từ ngày" htmlFor={ids.from}>
              <input id={ids.from} type="date" min={today} value={dateFrom} onChange={(e) => edit(setDateFrom, true)(e.target.value)} className={cn(inputCls, "tabular-nums")} />
            </Field>
            <Field label="Đến ngày" htmlFor={ids.to}>
              <input id={ids.to} type="date" min={dateFrom} value={dateTo} onChange={(e) => edit(setDateTo, true)(e.target.value)} className={cn(inputCls, "tabular-nums")} />
            </Field>
          </div>
          <fieldset className="w-full sm:w-auto">
            <legend className="mb-1.5 text-label font-semibold text-muted">Các thứ trong tuần</legend>
            <div className="flex justify-between gap-1.5 sm:justify-start">
              {DOW.map(([n, label]) => {
                const on = weekdays.includes(n);
                return (
                  <button
                    key={n}
                    type="button"
                    aria-pressed={on}
                    onClick={() => edit(setWeekdays, true)(on ? weekdays.filter((x) => x !== n) : [...weekdays, n])}
                    // Tròn 40px (điện thoại) / 36px (từ sm), vùng chạm ẩn ≥ 44px
                    className={cn(
                      "relative grid size-10 shrink-0 place-items-center rounded-full border text-sm font-semibold focus-ring transition-colors before:absolute before:-inset-0.5 motion-reduce:transition-none sm:size-9 sm:before:-inset-1",
                      on ? "border-primary bg-primary text-white" : "border-border-strong bg-surface hover:bg-primary-softer",
                    )}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </fieldset>
        </div>
      </Group>

      {/* 3. Các buổi + tiền: giảm giá cả đơn, tóm tắt dính + danh sách buổi (thao tác ngay trên dòng) */}
      <Group title="3. Các buổi & tiền">
        {/* Giảm giá đầu phần 3 (trước tóm tắt n buổi · m lỗi); đổi % ⇒ xem trước tính lại, giá ở chân hộp cập nhật */}
        <div className="w-40">
          <Field label="Giảm giá cả đơn (%)" htmlFor={ids.pct}>
            <input id={ids.pct} inputMode="numeric" value={pct} onChange={(e) => edit(setPct)(e.target.value.replace(/[^\d]/g, "").slice(0, 3))} className={inputCls} />
          </Field>
        </div>
        {!previewBody ? (
          <p className="text-sm text-muted">Để xem các buổi và tiền: {scheduleError.charAt(0).toLowerCase() + scheduleError.slice(1)}.</p>
        ) : !preview ? (
          <p className="text-sm text-muted" role="status">
            Đang kiểm lịch từng buổi…
          </p>
        ) : null}
        <SessionsPanel
          // Đang tính lại: giữ danh sách cũ (làm mờ) để các buổi và ô đang sửa không biến mất
          preview={preview ?? (calculating ? (result?.data ?? null) : null)}
          calculating={calculating}
          resources={resources}
          columns={calendar.columns}
          tweaks={tweaks}
          removedDays={removedDays}
          editingDay={editingDay}
          setEditingDay={setEditingDay}
          setTweak={setTweak}
          applySuggestion={applySuggestion}
          checkSession={checkSession}
          showOk={showOk}
          setShowOk={setShowOk}
        />
      </Group>

      {serverConflicts.length > 0 ? (
        <section aria-label="Buổi không đặt được">
          <ErrorBanner>
            Có {serverConflicts.length} buổi không đặt được, chưa tạo buổi nào. Đổi lịch, bảng xem trước sẽ tự cập nhật.
            <ul className="mt-1 list-disc pl-5">
              {serverConflicts.map((c) => (
                <li key={`${c.date}-${c.start}`}>
                  {dowName(c.date)} {formatDayMonthYear(c.date)} {hhmm(c.start)}: {c.reason_text ?? reasonText(c.reason)}
                </li>
              ))}
            </ul>
          </ErrorBanner>
        </section>
      ) : null}

    </Modal>
  );
}
