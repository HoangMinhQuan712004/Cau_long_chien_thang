"use client";

import { useEffect, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { errorText, write, type ApiError } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatLongDate, formatVnd } from "@/lib/format";
import {
  CustomerPicker,
  customerErrors,
  customerPayload,
  emptyCustomer,
  type CustomerErrors,
  type CustomerState,
} from "./customer-picker";
import { blockKey, hourText, type Block } from "./block";
import { getQuote, sendCounterBooking } from "./requests";
import type { Calendar, CounterOrder, Quote, Selection } from "./types";
import { btnCls, btnPrimaryCls, ErrorBanner, Hint, SummaryBox } from "./ui";


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
// Đặt sân tại quầy: một đơn gồm 1–20 khối cùng ngày (chọn nhiều ô trên lưới – T-025; bỏ từng khối trong popup)
// ---------------------------------------------------------------------------------------------

type BookingProps = {
  selection: Selection;
  /** Chọn nhiều ô trên lưới (T-025): các khối đã gom sẵn; không có thì dùng một khối từ `selection`. */
  initialBlocks?: Block[];
  /** Lịch đang xem: tên sân. */
  calendar: Calendar;
  onClose: () => void;
  /** Đã ghi thành công (cha tải lại lịch, tô sáng đơn mới). */
  onBooked: (order: CounterOrder) => void;
  /** Dữ liệu đổi ở máy khác (E-010…): cha đóng popup và tải lại lịch. */
  onStale: () => void;
  /** Chỉ tải lại lịch, giữ popup (sau 409 E-003: khối trùng được đánh dấu để bỏ đi). */
  onRefresh: () => void;
};

export function BookingDialog({ selection, initialBlocks, calendar, onClose, onBooked, onStale, onRefresh }: BookingProps) {
  const [blocks, setBlocks] = useState<Block[]>(() => initialBlocks?.length ? initialBlocks : [{ resource_code: selection.resourceCodes[0], start_hour: selection.startHour, end_hour: selection.endHour }]);
  const [quotes, setQuotes] = useState<Record<string, Quote | string>>({});
  const [conflicts, setConflicts] = useState<string[]>([]);
  const [customer, setCustomer] = useState<CustomerState>(emptyCustomer);
  const [serverErrors, setServerErrors] = useState<CustomerErrors>({});
  const [submitted, setSubmitted] = useState(false);
  const [banner, setBanner] = useState("");
  const [busy, setBusy] = useState(false);
  const names = Object.fromEntries(calendar.resources.map((r) => [r.code, r.name]));

  // Giá từng khối (bỏ khối thì giữ giá các khối còn lại)
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

      <CustomerPicker
        state={customer}
        onChange={setCustomer}
        submitted={submitted}
        serverErrors={serverErrors}
      />
      <Hint>Khách thanh toán tại quầy sau khi chơi — booking được tạo ở trạng thái Chưa thanh toán.</Hint>
    </Modal>
  );
}
