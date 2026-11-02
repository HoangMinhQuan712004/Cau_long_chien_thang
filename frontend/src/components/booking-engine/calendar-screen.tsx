"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { cellKey } from "@/components/court-grid/court-grid";
import { errorText } from "@/lib/api/write";
import { normalizeBookingCode } from "@/lib/booking-code";
import { toast } from "@/lib/feedback";
import { addDaysIso, formatLongDate, formatVnd, vnDate } from "@/lib/format";
import { AdminGrid, EVENT_RECT_HINT, isSellable, selectionBlocks, selectionRect } from "./admin-grid";
import { MAX_BLOCKS, type Block } from "./block-adder";
import { BookingDialog, SessionFormDialog } from "./booking-dialogs";
import { ItemFlow } from "./item-flow";
import { OrderFlow } from "./order-flow";
import { getCalendar, searchCode } from "./requests";
import { SessionFlow } from "./session-flow";
import type { Calendar, CalendarBlock, Selection } from "./types";
import { inputCls } from "./ui";

// Màn Đặt sân (/admin/dat-san): lịch ngày + các hộp thoại. Dữ liệu đầu lấy ở server; sau đó tải lại ở client:
// mỗi 30 giây khi tab đang hiển thị (NFR-002) và ngay sau mỗi thao tác ghi.

type Dialog =
  | { kind: "booking"; selection: Selection; blocks: Block[] }
  | { kind: "order"; orderCode: string }
  | { kind: "sessionForm"; selection: Selection }
  | { kind: "item"; code: string }
  | { kind: "session"; code: string };

const REFRESH_MS = 30_000;

export function CalendarScreen({ initial, role }: { initial: Calendar; role: "admin" | "staff" }) {
  const [calendar, setCalendar] = useState(initial);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [onlyUnpaid, setOnlyUnpaid] = useState(false);
  const [highlight, setHighlight] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [searchError, setSearchError] = useState("");
  // Ô đang chọn trên lưới (bấm từng ô, T-025): khóa "mã sân|giờ"
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set());
  const dateRef = useRef(initial.date);
  const isAdmin = role === "admin";

  const today = vnDate(calendar.now);
  const unpaidOnly = onlyUnpaid && calendar.unpaid_count > 0; // n = 0 → tự về Tất cả

  /** Tải lịch của một ngày; trả về true nếu thành công. */
  const load = useCallback(async (date: string, opts?: { quiet?: boolean }): Promise<boolean> => {
    if (!opts?.quiet) setLoading(true);
    const res = await getCalendar(date);
    if (!opts?.quiet) setLoading(false);
    if (!res.ok) {
      if (!opts?.quiet) toast(errorText(res.error), undefined, "error");
      return false;
    }
    if (dateRef.current === date) setCalendar(res.data);
    return true;
  }, []);

  const goto = useCallback(
    async (date: string) => {
      const prev = dateRef.current;
      setSelected(new Set());
      dateRef.current = date;
      if (!(await load(date))) dateRef.current = prev;
      else window.history.replaceState(null, "", `?date=${date}`);
    },
    [load],
  );

  const refresh = useCallback(() => void load(dateRef.current, { quiet: true }), [load]);

  // Tự làm mới mỗi 30 giây khi tab đang hiển thị; làm mới ngay khi quay lại tab
  useEffect(() => {
    const tick = () => {
      if (document.visibilityState === "visible") refresh();
    };
    const id = setInterval(tick, REFRESH_MS);
    document.addEventListener("visibilitychange", tick);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [refresh]);

  // Xóa tô sáng sau vài giây
  useEffect(() => {
    if (!highlight) return;
    const t = setTimeout(() => setHighlight(null), 4000);
    return () => clearTimeout(t);
  }, [highlight]);

  const names = Object.fromEntries(calendar.resources.map((r) => [r.code, r.name]));

  // Lịch tải lại (30 giây / sau thao tác): bỏ khỏi vùng chọn các ô vừa có người đặt hoặc không còn bán
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- đồng bộ vùng chọn với lịch mới tải
    setSelected((cur) => {
      const kept = [...cur].filter((k) => {
        const [code, h] = k.split("|");
        return isSellable(calendar, code, Number(h));
      });
      return kept.length === cur.size ? cur : new Set(kept);
    });
  }, [calendar]);

  const toggle = useCallback((code: string, hour: number) => {
    setSelected((cur) => {
      const next = new Set(cur);
      const k = cellKey(code, hour);
      if (!next.delete(k)) next.add(k);
      return next;
    });
  }, []);
  const clear = useCallback(() => setSelected(new Set()), []);

  const onBlockClick = useCallback((b: CalendarBlock) => {
    if (b.type === "booking" && b.code) setDialog({ kind: "item", code: b.code });
    else if (b.type === "session" && b.code) setDialog({ kind: "session", code: b.code });
    else if (b.type === "hold") {
      toast("Khung đang được giữ cho khách đặt online", "Hết 5 phút giữ chỗ mà khách chưa đặt xong thì khung trống lại.", "info");
    }
  }, []);

  // Quyền đặt quầy / tạo sự kiện của NGÀY đang xem do server quyết (`calendar.can`), không tự suy ra từ ngày hay tháng ở client.
  const canPick = !calendar.is_past && (calendar.can.counter_book || calendar.can.create_session);
  const blocks = selectionBlocks(calendar, selected);
  const rect = selectionRect(calendar, selected, calendar.date);
  const total = calendar.resources.reduce(
    (sum, r) => sum + calendar.columns.reduce((n, h) => n + (selected.has(cellKey(r.code, h)) ? (r.hour_prices?.[String(h)] ?? 0) : 0), 0),
    0,
  );
  const bookReason = !calendar.can.counter_book
    ? "Đặt sân tại quầy chỉ cho hôm nay."
    : blocks.length > MAX_BLOCKS
      ? `Một đơn tối đa ${MAX_BLOCKS} khối. Bỏ bớt ô hoặc nối các giờ liền nhau.`
      : "";
  const eventReason = !calendar.can.create_session ? "Không tạo được sự kiện ở ngày này." : !rect ? EVENT_RECT_HINT : "";

  function openBooking() {
    if (!blocks.length || bookReason) return;
    const f = blocks[0];
    setDialog({ kind: "booking", selection: { resourceCodes: [f.resource_code], date: calendar.date, startHour: f.start_hour, endHour: f.end_hour }, blocks });
  }
  function openSessionForm() {
    if (rect && !eventReason) setDialog({ kind: "sessionForm", selection: rect });
  }

  async function onSearch(e: React.FormEvent) {
    e.preventDefault();
    const code = normalizeBookingCode(query);
    if (!code) return;
    const res = await searchCode(code);
    if (!res.ok) {
      setSearchError(res.error.code === "E-021" || res.error.status === 404 ? `Không tìm thấy mã ${code}. Kiểm tra lại mã.` : errorText(res.error));
      return;
    }
    setSearchError("");
    const { kind, play_date } = res.data;
    if (play_date !== dateRef.current) await goto(play_date);
    // Mã đơn → danh sách các khối của đơn; mã khối (mã con) → chi tiết khối
    if (kind === "order") {
      setHighlight(res.data.order_code ?? res.data.code);
      setDialog({ kind: "order", orderCode: res.data.order_code ?? res.data.code });
      return;
    }
    setHighlight(kind === "ticket" ? null : res.data.code);
    setDialog(kind === "session" ? { kind: "session", code: res.data.code } : { kind: "item", code: res.data.code });
  }

  const isToday = calendar.date === today;
  const footText = calendar.is_past
    ? "Ngày đã qua: chỉ xem, không chọn khung mới. Bấm khối để xem Thông tin booking."
    : !canPick
      ? "Tài khoản tại máy chỉ đặt sân trong hôm nay. Ngày khác do Admin đặt. Bấm khối để xem chi tiết."
      : isAdmin
        ? "Bấm từng ô trống để chọn (nhiều sân, nhiều giờ) rồi Đặt sân hoặc Tạo sự kiện · bấm khối để xem chi tiết · Esc bỏ chọn."
        : "Bấm từng ô trống để chọn (nhiều sân, nhiều giờ) rồi Đặt sân · bấm khối để xem chi tiết · Esc bỏ chọn.";

  const chip = (active: boolean) =>
    `rounded-full border px-3 py-1.5 text-sm ${active ? "border-primary bg-primary text-white" : "border-border bg-surface hover:bg-primary-softer"}`;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold">Đặt sân</h1>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={() => goto(addDaysIso(calendar.date, -1))}
            aria-label="Ngày trước"
            className="grid size-9 place-items-center rounded-lg border border-border bg-surface hover:bg-primary-softer"
          >
            ‹
          </button>
          <span className="min-w-36 text-center text-sm font-medium" aria-live="polite">
            {formatLongDate(calendar.date)}
          </span>
          <button
            type="button"
            onClick={() => goto(addDaysIso(calendar.date, 1))}
            aria-label="Ngày sau"
            className="grid size-9 place-items-center rounded-lg border border-border bg-surface hover:bg-primary-softer"
          >
            ›
          </button>
          <button
            type="button"
            onClick={() => goto(today)}
            disabled={isToday}
            className="rounded-lg border border-border bg-surface px-3 py-2 text-sm hover:bg-primary-softer disabled:opacity-50"
          >
            Hôm nay
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-muted">
        <Legend swatch="bg-cell-off" label="Xám = ngoài giờ mở cửa hoặc sân ngừng hoạt động" text="Xám" />
        <Legend swatch="bg-blk-session" label="Tím" text="Tím = Sự kiện" />
        <Legend swatch="border border-border bg-surface" label="Trắng" text="Trắng = Trống" />
        <Legend swatch="bg-primary" label="Xanh" text="Xanh = Đang chọn" />
        <Legend swatch="bg-blk-paid" label="Đỏ" text="Đỏ = Đã đặt" />
        <Legend swatch="bg-blk-unpaid" label="Vàng" text="Vàng = Chưa thanh toán" />
        <div className="ml-auto flex items-center gap-2">
          <span>Hiển thị:</span>
          <button type="button" onClick={() => setOnlyUnpaid(false)} aria-pressed={!unpaidOnly} className={chip(!unpaidOnly)}>
            Tất cả
          </button>
          <button
            type="button"
            onClick={() => setOnlyUnpaid(true)}
            disabled={calendar.unpaid_count === 0}
            aria-pressed={unpaidOnly}
            className={`${chip(unpaidOnly)} disabled:opacity-50`}
          >
            Chưa thanh toán ({calendar.unpaid_count})
          </button>
        </div>
      </div>

      <form onSubmit={onSearch} className="flex flex-wrap items-start gap-2" role="search">
        <div>
          <label htmlFor="code-search" className="sr-only">
            Tìm theo mã đơn, mã khối, sự kiện hoặc vé
          </label>
          <input
            id="code-search"
            value={query}
            placeholder="Tìm mã BK-20261020-021…"
            maxLength={40}
            onChange={(e) => {
              setQuery(e.target.value);
              setSearchError("");
            }}
            aria-invalid={Boolean(searchError) || undefined}
            className={`${inputCls} w-64`}
          />
          {searchError ? (
            <p role="alert" className="mt-1 text-xs text-danger">
              {searchError}
            </p>
          ) : null}
        </div>
        <button type="submit" className="rounded-lg border border-border bg-surface px-3 py-2 text-sm hover:bg-primary-softer">
          Tìm
        </button>
        {unpaidOnly ? (
          <p className="self-center text-sm text-muted">
            Đang lọc: Chưa thanh toán · {calendar.unpaid_count}.{" "}
            <button type="button" onClick={() => setOnlyUnpaid(false)} className="text-primary hover:underline">
              Bỏ lọc
            </button>
          </p>
        ) : null}
      </form>

      <div className={loading ? "opacity-60 transition-opacity" : "transition-opacity"} aria-busy={loading}>
        <AdminGrid
          calendar={calendar}
          selected={selected}
          selectable={canPick && dialog === null}
          unpaidOnly={unpaidOnly}
          highlightCode={highlight}
          onToggle={toggle}
          onClear={clear}
          onBlockClick={onBlockClick}
          onHoldExpired={refresh}
        />
      </div>
      <p className="text-sm text-muted">{footText}</p>

      {selected.size > 0 ? (
        <section data-bottom-bar className="sticky bottom-3 z-20 rounded-2xl border border-border bg-surface p-3 shadow-lg" aria-label="Khung đang chọn">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <p className="min-w-0 flex-1 text-sm font-semibold tabular-nums" aria-live="polite">
              {selected.size} khung · {formatVnd(total)}
              <span className="ml-2 text-xs font-normal text-muted">Tạm tính theo bảng giá; giá chốt khi đặt.</span>
            </p>
            <button type="button" onClick={clear} className="min-h-10 rounded-lg border border-border px-4 text-sm hover:bg-primary-softer">
              Bỏ chọn
            </button>
            <button
              type="button"
              onClick={openBooking}
              disabled={Boolean(bookReason)}
              title={bookReason || undefined}
              className="min-h-10 rounded-lg bg-primary px-5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"
            >
              Đặt sân
            </button>
            {isAdmin ? (
              <button
                type="button"
                onClick={openSessionForm}
                disabled={Boolean(eventReason)}
                title={eventReason || undefined}
                className="min-h-10 rounded-lg border border-primary px-5 text-sm font-semibold text-primary disabled:cursor-not-allowed disabled:opacity-40"
              >
                Tạo sự kiện
              </button>
            ) : null}
          </div>
          {bookReason || (isAdmin && eventReason) ? (
            <p className="mt-1.5 text-xs text-muted">{[bookReason, isAdmin ? eventReason : ""].filter(Boolean).join(" · ")}</p>
          ) : null}
        </section>
      ) : null}

      {dialog?.kind === "booking" ? (
        <BookingDialog
          selection={dialog.selection}
          initialBlocks={dialog.blocks}
          calendar={calendar}
          onRefresh={refresh}
          canSession={isAdmin}
          onClose={() => setDialog(null)}
          onSwitchToSession={() => setDialog({ kind: "sessionForm", selection: rect ?? dialog.selection })}
          onBooked={(order) => {
            setDialog(null);
            clear();
            setHighlight(order.order_code);
            refresh();
          }}
          onStale={() => {
            setDialog(null);
            refresh();
          }}
        />
      ) : null}
      {dialog?.kind === "sessionForm" ? (
        <SessionFormDialog
          selection={dialog.selection}
          resourceNames={names}
          onClose={() => setDialog(null)}
          onCreated={() => {
            setDialog(null);
            clear();
            refresh();
          }}
          onStale={() => {
            setDialog(null);
            refresh();
          }}
        />
      ) : null}
      {dialog?.kind === "item" ? (
        <ItemFlow
          key={dialog.code}
          code={dialog.code}
          onClose={() => setDialog(null)}
          onChanged={refresh}
          onOpenSession={(code) => setDialog({ kind: "session", code })}
          onOpenOrder={(orderCode) => setDialog({ kind: "order", orderCode })}
        />
      ) : null}
      {dialog?.kind === "order" ? (
        <OrderFlow
          key={dialog.orderCode}
          orderCode={dialog.orderCode}
          onClose={() => setDialog(null)}
          onChanged={refresh}
          onOpenItem={(code) => setDialog({ kind: "item", code })}
        />
      ) : null}
      {dialog?.kind === "session" ? (
        <SessionFlow
          key={dialog.code}
          code={dialog.code}
          onClose={() => setDialog(null)}
          onChanged={refresh}
          onOpenTicket={(code) => setDialog({ kind: "item", code })}
        />
      ) : null}
    </div>
  );
}

function Legend({ swatch, label, text }: { swatch: string; label: string; text: string }) {
  return (
    <span className="inline-flex items-center gap-1.5" title={label}>
      <span aria-hidden className={`inline-block size-3.5 rounded-sm ${swatch}`} />
      {text}
    </span>
  );
}
