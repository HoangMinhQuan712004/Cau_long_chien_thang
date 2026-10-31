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
import { BlockAdder, blockKey, hourText, MAX_BLOCKS, type Block } from "./block-adder";
import { getQuote, sendCounterBooking, sendCreateSession } from "./requests";
import type { Calendar, CounterOrder, Quote, Selection } from "./types";
import { btnCls, btnPrimaryCls, ErrorBanner, Hint, inputCls, SummaryBox } from "./ui";


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
// Đặt sân tại quầy: một đơn gồm 1–20 khối cùng ngày (kéo chọn vùng đầu, rồi "+ Thêm khối" – T-019)
// ---------------------------------------------------------------------------------------------

type BookingProps = {
  selection: Selection;
  /** Lịch đang xem: nguồn giờ trống cho "+ Thêm khối" và tên sân. */
  calendar: Calendar;
  /** Admin: có tab "Đặt sự kiện" trong popup. */
  canSession: boolean;
  onClose: () => void;
  onSwitchToSession: () => void;
  /** Đã ghi thành công (cha tải lại lịch, tô sáng đơn mới). */
  onBooked: (order: CounterOrder) => void;
  /** Dữ liệu đổi ở máy khác (E-010…): cha đóng popup và tải lại lịch. */
  onStale: () => void;
  /** Chỉ tải lại lịch, giữ popup (sau 409 E-003: khối trùng được đánh dấu để bỏ đi). */
  onRefresh: () => void;
};

export function BookingDialog({ selection, calendar, canSession, onClose, onSwitchToSession, onBooked, onStale, onRefresh }: BookingProps) {
  const [blocks, setBlocks] = useState<Block[]>(() => [{ resource_code: selection.resourceCodes[0], start_hour: selection.startHour, end_hour: selection.endHour }]);
  const [quotes, setQuotes] = useState<Record<string, Quote | string>>({});
  const [adding, setAdding] = useState(false);
  const [conflicts, setConflicts] = useState<string[]>([]);
  const [customer, setCustomer] = useState<CustomerState>(emptyCustomer);
  const [serverErrors, setServerErrors] = useState<CustomerErrors>({});
  const [submitted, setSubmitted] = useState(false);
  const [banner, setBanner] = useState("");
  const [busy, setBusy] = useState(false);
  const names = Object.fromEntries(calendar.resources.map((r) => [r.code, r.name]));

  // Giá từng khối (khối mới thêm thì tính tiếp, khối đã có giữ nguyên)
  useEffect(() => {
    let live = true;
    for (const bl of blocks) {
      const k = blockKey(bl);
      getQuote(bl.resource_code, selection.date, bl.start_hour, bl.end_hour).then((res) => {
        if (live) setQuotes((q) => ({ ...q, [k + "|" + bl.end_hour]: res.ok ? res.data : errorText(res.error) }));
      });
    }
    return () => {
      live = false;
    };
  }, [blocks, selection.date]);

  const quoteOf = (bl: Block) => quotes[blockKey(bl) + "|" + bl.end_hour];
  const allQuoted = blocks.every((bl) => typeof quoteOf(bl) === "object");
  const total = blocks.reduce((n, bl) => {
    const q = quoteOf(bl);
    return typeof q === "object" ? n + q.total_amount : n;
  }, 0);
  const canSubmit = (customer.mode === "temp" || customer.picked !== null) && allQuoted && blocks.length > 0;

  async function submit() {
    setSubmitted(true);
    setBanner("");
    setServerErrors({});
    setConflicts([]);
    const errors = customerErrors(customer);
    const payload = customerPayload(customer);
    if (Object.keys(errors).length || !payload) return;
    setBusy(true);
    try {
      const res = await write((key) => sendCounterBooking(key, { date: selection.date, blocks, customer: payload }));
      if (!res.ok) {
        const e = res.error;
        if (authFailure(e)) return;
        // E-003: có khối trùng lịch (không khối nào được tạo) → đánh dấu khối trùng, người dùng bỏ khối đó rồi đặt lại
        if (e.code === "E-003" && Array.isArray(e.extra.conflicts)) {
          const hit = e.extra.conflicts as { resource_code: string; start_hour: number }[];
          setConflicts(blocks.filter((bl) => hit.some((c) => c.resource_code === bl.resource_code && c.start_hour >= bl.start_hour && c.start_hour < bl.end_hour)).map(blockKey));
          setBanner("Có khối đã có người đặt. Bỏ các khối đánh dấu đỏ rồi đặt lại; chưa có khối nào được tạo.");
          onRefresh();
          return;
        }
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
      const first = order.bookings[0];
      const where = order.bookings.length === 1 ? ` · ${names[blocks[0].resource_code] ?? ""} · ${hourText(blocks[0].start_hour)}–${hourText(blocks[0].end_hour)}` : ` · ${order.bookings.length} khối`;
      toast(`Đã đặt ${order.order_code}${where} cho ${first.customer.name}`, "Trạng thái: Chưa thanh toán · thu tiền tại quầy sau khi chơi");
      onBooked(order);
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
          <button type="button" onClick={submit} disabled={busy || !canSubmit} className={btnPrimaryCls}>
            {busy ? "Đang đặt…" : blocks.length > 1 ? `Đặt ${blocks.length} khối` : "Đặt sân"}
          </button>
        </>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
      <SummaryBox>
        <p className="text-muted">{formatLongDate(selection.date)}</p>
        <ul className="divide-y divide-border">
          {blocks.map((bl) => {
            const q = quoteOf(bl);
            const bad = conflicts.includes(blockKey(bl));
            return (
              <li key={blockKey(bl)} className={`flex items-center gap-3 py-2 ${bad ? "text-danger" : ""}`}>
                <span className="min-w-0 flex-1">
                  <span className="font-semibold">
                    {bl.resource_code} · {names[bl.resource_code] ?? ""}
                  </span>
                  <span className="block text-sm">
                    {hourText(bl.start_hour)}–{hourText(bl.end_hour)}
                    {bad ? " · đã có người đặt" : typeof q === "object" ? ` · ${q.items.map((it) => it.label).filter((v, i, arr) => arr.indexOf(v) === i).join(", ")}` : ""}
                  </span>
                </span>
                <span className="tabular-nums">
                  {typeof q === "object" ? formatVnd(q.total_amount) : typeof q === "string" ? <span className="text-danger">Lỗi giá</span> : "…"}
                </span>
                {blocks.length > 1 ? (
                  <button
                    type="button"
                    aria-label={`Bỏ khối ${bl.resource_code} ${hourText(bl.start_hour)}–${hourText(bl.end_hour)}`}
                    onClick={() => {
                      setBlocks((all) => all.filter((x) => blockKey(x) !== blockKey(bl)));
                      setConflicts((c) => c.filter((k) => k !== blockKey(bl)));
                    }}
                    className="grid size-11 shrink-0 place-items-center rounded-md text-muted hover:text-danger sm:size-8"
                  >
                    ✕
                  </button>
                ) : null}
              </li>
            );
          })}
        </ul>
        {blocks.some((bl) => typeof quoteOf(bl) === "string") ? (
          <p role="alert" className="text-danger">
            {String(blocks.map(quoteOf).find((q) => typeof q === "string"))}
          </p>
        ) : null}
        <div className="flex gap-3 border-t border-border pt-1.5 font-semibold">
          <span>Tiền sân</span>
          <span className="ml-auto tabular-nums">{allQuoted ? formatVnd(total) : "đang tính giá…"}</span>
        </div>
      </SummaryBox>

      {adding ? (
        <BlockAdder
          calendar={calendar}
          chosen={blocks}
          onCancel={() => setAdding(false)}
          onAdd={(b) => {
            setBlocks((all) => [...all, b]);
            setAdding(false);
          }}
        />
      ) : blocks.length < MAX_BLOCKS ? (
        <button type="button" onClick={() => setAdding(true)} className={`${btnCls} h-11 w-full border-dashed sm:h-auto`}>
          + Thêm khối
        </button>
      ) : (
        <Hint>Tối đa {MAX_BLOCKS} khối một đơn.</Hint>
      )}

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
        <ReadOnly label="Từ – Đến" value={`${hourText(selection.startHour)} – ${hourText(selection.endHour)}`} />
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
