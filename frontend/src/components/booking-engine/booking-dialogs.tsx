"use client";

import { useEffect, useId, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { errorText, write, type ApiError } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatLongDate, formatNumber, formatVnd } from "@/lib/format";
import {
  CustomerPicker,
  customerErrors,
  customerPayload,
  emptyCustomer,
  type CustomerErrors,
  type CustomerState,
} from "./customer-picker";
import { getQuote, sendCounterBooking, sendCreateSession } from "./requests";
import type { CounterOrder, Item, Quote, Selection } from "./types";
import { btnCls, btnPrimaryCls, ErrorBanner, Hint, inputCls, SummaryBox } from "./ui";

const pad2 = (n: number) => String(n).padStart(2, "0");
const range = (s: Selection) => `${pad2(s.startHour)}:00–${pad2(s.endHour)}:00`;

/** Lỗi cho biết dữ liệu đã đổi ở máy khác: đóng hộp thoại và tải lại lịch (T-006 §9). */
export const STALE_CODES = ["E-003", "E-010", "E-012", "E-023", "E-024"];

/** 401/403 báo bằng toast (không gắn vào form). Trả true nếu đã xử lý. */
export function authFailure(error: ApiError): boolean {
  if (error.status === 401 || error.status === 403) {
    toast(errorText(error), undefined, "error");
    return true;
  }
  return false;
}

// ---------------------------------------------------------------------------------------------
// Đặt sân tại quầy (1 sân, hôm nay, các khung liền nhau)
// ---------------------------------------------------------------------------------------------

type BookingProps = {
  selection: Selection;
  /** Admin: có tab "Đặt sự kiện" trong popup. */
  canSession: boolean;
  onClose: () => void;
  onSwitchToSession: () => void;
  /** Đã ghi thành công (cha tải lại lịch, tô sáng khối mới). */
  onBooked: (item: Item) => void;
  /** Dữ liệu đổi ở máy khác (E-003…): cha tải lại lịch. */
  onStale: () => void;
};

export function BookingDialog({ selection, canSession, onClose, onSwitchToSession, onBooked, onStale }: BookingProps) {
  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoteError, setQuoteError] = useState("");
  const [customer, setCustomer] = useState<CustomerState>(emptyCustomer);
  const [serverErrors, setServerErrors] = useState<CustomerErrors>({});
  const [submitted, setSubmitted] = useState(false);
  const [banner, setBanner] = useState("");
  const [busy, setBusy] = useState(false);
  const code = selection.resourceCodes[0];

  useEffect(() => {
    let live = true;
    getQuote(code, selection.date, selection.startHour, selection.endHour).then((res) => {
      if (!live) return;
      if (res.ok) setQuote(res.data);
      else setQuoteError(errorText(res.error));
    });
    return () => {
      live = false;
    };
  }, [code, selection.date, selection.startHour, selection.endHour]);

  const canSubmit = customer.mode === "temp" || customer.picked !== null;

  async function submit() {
    setSubmitted(true);
    setBanner("");
    setServerErrors({});
    const errors = customerErrors(customer);
    const payload = customerPayload(customer);
    if (Object.keys(errors).length || !payload) return;
    setBusy(true);
    try {
      const res = await write((key) =>
        sendCounterBooking(key, {
          date: selection.date,
          blocks: [{ resource_code: code, start_hour: selection.startHour, end_hour: selection.endHour }],
          customer: payload,
        }),
      );
      if (!res.ok) {
        const e = res.error;
        if (authFailure(e)) return;
        if (e.code && STALE_CODES.includes(e.code)) {
          toast(errorText(e), undefined, "error");
          onStale();
          return;
        }
        if (e.code === "E-018" || e.code === "E-002") setServerErrors({ phone: errorText(e) });
        else if (e.code === "E-014") setServerErrors({ pick: errorText(e) });
        else setBanner(errorText(e));
        return;
      }
      const order = res.data as CounterOrder;
      const item = order.bookings[0];
      toast(
        `Đã đặt ${order.order_code} · ${quote?.resource_name ?? ""} · ${range(selection)} cho ${item.customer.name}`,
        "Trạng thái: Chưa thanh toán · thu tiền tại quầy sau khi chơi",
      );
      onBooked(item);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title="Đặt sân"
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy} className={btnCls}>
            Hủy
          </button>
          <button type="button" onClick={submit} disabled={busy || !canSubmit || !quote} className={btnPrimaryCls}>
            {busy ? "Đang đặt…" : "Đặt sân"}
          </button>
        </>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
      <SummaryBox>
        {quote ? (
          <>
            <p className="font-semibold">
              {quote.resource_code} · {quote.resource_name}
            </p>
            <p className="text-muted">{formatLongDate(quote.date)}</p>
            {quote.items.map((it) => (
              <div key={it.start_time} className="flex gap-3">
                <span>
                  {it.start_time.slice(0, 5)}–{it.end_time.slice(0, 5)} · {it.label}
                </span>
                <span className="ml-auto tabular-nums">{formatVnd(it.price)}</span>
              </div>
            ))}
            <div className="flex gap-3 border-t border-border pt-1.5 font-semibold">
              <span>Tiền sân</span>
              <span className="ml-auto tabular-nums">{formatVnd(quote.total_amount)}</span>
            </div>
          </>
        ) : quoteError ? (
          <p role="alert" className="text-danger">
            {quoteError}
          </p>
        ) : (
          <p className="text-muted">
            {code} · {formatLongDate(selection.date)} · {range(selection)} — đang tính giá…
          </p>
        )}
      </SummaryBox>

      <CustomerPicker
        state={customer}
        onChange={setCustomer}
        submitted={submitted}
        serverErrors={serverErrors}
        onPickSession={canSession ? onSwitchToSession : undefined}
      />
      <Hint>Khách thanh toán tại quầy sau khi chơi — booking được tạo ở trạng thái Chưa thanh toán.</Hint>
    </Modal>
  );
}

// ---------------------------------------------------------------------------------------------
// Đặt sự kiện (Admin): một hoặc nhiều sân liền nhau, hoặc ngày sau
// ---------------------------------------------------------------------------------------------

type SessionFormProps = {
  selection: Selection;
  /** Tên sân theo mã để hiển thị. */
  resourceNames: Record<string, string>;
  onClose: () => void;
  onCreated: () => void;
  onStale: () => void;
};

const digits = (v: string) => v.replace(/\D/g, "");

export function SessionFormDialog({ selection, resourceNames, onClose, onCreated, onStale }: SessionFormProps) {
  const ids = { name: useId(), capacity: useId(), price: useId() };
  const [name, setName] = useState("");
  const [capacity, setCapacity] = useState("");
  const [price, setPrice] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [banner, setBanner] = useState("");
  const [busy, setBusy] = useState(false);

  const errName = !name.trim() ? "Vui lòng nhập Tên sự kiện." : name.trim().length > 100 ? "Tên sự kiện tối đa 100 ký tự." : "";
  const cap = Number(capacity);
  const errCap = !capacity ? "Vui lòng nhập Số chỗ tối đa." : cap < 1 || cap > 99 ? "Số chỗ tối đa là số nguyên từ 1 đến 99." : "";
  const errPrice = price === "" ? "Vui lòng nhập Giá vé." : "";

  async function submit() {
    setSubmitted(true);
    setBanner("");
    if (errName || errCap || errPrice) return;
    setBusy(true);
    try {
      const res = await write((key) =>
        sendCreateSession(key, {
          resource_codes: selection.resourceCodes,
          date: selection.date,
          start_hour: selection.startHour,
          end_hour: selection.endHour,
          name: name.trim(),
          capacity: cap,
          ticket_price: Number(price),
        }),
      );
      if (!res.ok) {
        const e = res.error;
        if (authFailure(e)) return;
        if (e.code && STALE_CODES.includes(e.code)) {
          toast(errorText(e), undefined, "error");
          onStale();
          return;
        }
        setBanner(errorText(e));
        return;
      }
      toast(`Đã lưu sự kiện "${name.trim()}" · ${cap} chỗ · ${formatVnd(Number(price))} / người.`);
      onCreated();
    } finally {
      setBusy(false);
    }
  }

  const names = selection.resourceCodes.map((c) => `${c} · ${resourceNames[c] ?? ""}`).join(", ");
  return (
    <Modal
      open
      onClose={onClose}
      title="Đặt sự kiện"
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy} className={btnCls}>
            Hủy
          </button>
          <button type="button" onClick={submit} disabled={busy} className={btnPrimaryCls}>
            {busy ? "Đang lưu…" : "Lưu sự kiện"}
          </button>
        </>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
      <div>
        <label htmlFor={ids.name} className="mb-1 block text-sm font-medium">
          Tên sự kiện <span className="text-danger">*</span>
        </label>
        <input
          id={ids.name}
          value={name}
          maxLength={100}
          placeholder="Giao lưu tối thứ Ba"
          onChange={(e) => setName(e.target.value)}
          aria-invalid={Boolean(submitted && errName) || undefined}
          className={inputCls}
        />
        {submitted && errName ? <p className="mt-1 text-xs text-danger">{errName}</p> : null}
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <ReadOnly label="Ngày" value={formatLongDate(selection.date)} />
        <ReadOnly label="Từ – Đến" value={`${pad2(selection.startHour)}:00 – ${pad2(selection.endHour)}:00`} />
        <ReadOnly label="Số sân" value={`${selection.resourceCodes.length} sân`} />
      </div>
      <ReadOnly label="Sân" value={names} />
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor={ids.capacity} className="mb-1 block text-sm font-medium">
            Số chỗ tối đa <span className="text-danger">*</span>
          </label>
          <input
            id={ids.capacity}
            value={capacity}
            inputMode="numeric"
            maxLength={3}
            placeholder="1 – 99"
            onChange={(e) => setCapacity(digits(e.target.value))}
            aria-invalid={Boolean(submitted && errCap) || undefined}
            className={inputCls}
          />
          {submitted && errCap ? <p className="mt-1 text-xs text-danger">{errCap}</p> : null}
        </div>
        <div>
          <label htmlFor={ids.price} className="mb-1 block text-sm font-medium">
            Giá vé (đ / người) <span className="text-danger">*</span>
          </label>
          <input
            id={ids.price}
            value={price === "" ? "" : formatNumber(Number(price))}
            inputMode="numeric"
            placeholder="VD: 60.000"
            onChange={(e) => setPrice(digits(e.target.value).slice(0, 9))}
            aria-invalid={Boolean(submitted && errPrice) || undefined}
            className={inputCls}
          />
          {submitted && errPrice ? <p className="mt-1 text-xs text-danger">{errPrice}</p> : null}
        </div>
      </div>
      <Hint>Khung đã chọn được giữ cho sự kiện; khách đăng ký vé tại quầy hoặc trên web.</Hint>
    </Modal>
  );
}

function ReadOnly({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="mb-1 block text-sm font-medium">{label}</span>
      <p className="rounded-md border border-border bg-background px-3 py-2 text-sm text-muted">{value}</p>
    </div>
  );
}
