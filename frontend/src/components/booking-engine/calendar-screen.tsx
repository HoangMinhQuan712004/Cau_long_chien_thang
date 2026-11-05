"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { cellKey } from "@/components/court-grid/court-grid";
import { errorText } from "@/lib/api/write";
import { cn } from "@/lib/cn";
import { toast } from "@/lib/feedback";
import { vnDate } from "@/lib/format";
import { AdminGrid, EVENT_RECT_HINT, isSellable, selectionBlocks, selectionRect } from "./admin-grid";
import { MAX_BLOCKS, type Block } from "./block";
import { BookingDialog } from "./booking-dialogs";
import { CalendarToolbar } from "./calendar-toolbar";
import { ItemFlow } from "./item-flow";
import { OrderFlow } from "./order-flow";
import { RecurringDialog } from "./recurring-dialog";
import { SelectionBar } from "./selection-bar";
import { getCalendar, searchCode } from "./requests";
import { SessionFlow } from "./session-flow";
import { SessionFormDialog } from "./session-form-dialog";
import type { Calendar, CalendarBlock, Selection } from "./types";

// Màn Đặt sân (/admin/dat-san): lịch ngày + các hộp thoại. Dữ liệu đầu lấy ở server; sau đó tải lại ở client:
// mỗi 30 giây khi tab đang hiển thị (NFR-002) và ngay sau mỗi thao tác ghi.

type Dialog =
  | { kind: "booking"; selection: Selection; blocks: Block[] }
  | { kind: "order"; orderCode: string }
  | { kind: "sessionForm"; selection: Selection }
  | { kind: "recurring" }
  | { kind: "item"; code: string }
  | { kind: "session"; code: string };

const REFRESH_MS = 30_000;

/** `canRecurring`: quyền booking.recurring ⇒ hiện nút "Đặt sân định kỳ" (backend vẫn kiểm). */
export function CalendarScreen({ initial, canRecurring }: { initial: Calendar; canRecurring: boolean }) {
  const [calendar, setCalendar] = useState(initial);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [onlyUnpaid, setOnlyUnpaid] = useState(false);
  const [highlight, setHighlight] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // Ô đang chọn trên lưới (bấm từng ô, T-025): khóa "mã sân|giờ"
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set());
  const dateRef = useRef(initial.date);
  // Tạo / xóa sự kiện: cờ do backend tính theo quyền booking.session.manage (không so vai)
  const canSession = calendar.can.create_session;

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

  /** Tìm mã (ô tìm ở thanh công cụ): trả câu lỗi, "" = tìm thấy (chuyển ngày + mở hộp chi tiết). */
  async function findCode(code: string): Promise<string> {
    const res = await searchCode(code);
    if (!res.ok) return res.error.code === "E-021" || res.error.status === 404 ? `Không tìm thấy mã ${code}. Kiểm tra lại mã.` : errorText(res.error);
    const { kind, play_date } = res.data;
    if (play_date !== dateRef.current) await goto(play_date);
    // Mã đơn → danh sách các khối của đơn; mã khối (mã con) → chi tiết khối
    if (kind === "order") {
      setHighlight(res.data.order_code ?? res.data.code);
      setDialog({ kind: "order", orderCode: res.data.order_code ?? res.data.code });
      return "";
    }
    setHighlight(kind === "ticket" ? null : res.data.code);
    setDialog(kind === "session" ? { kind: "session", code: res.data.code } : { kind: "item", code: res.data.code });
    return "";
  }

  const footText = calendar.is_past
    ? "Ngày đã qua: chỉ xem, không chọn khung mới. Bấm khối để xem Thông tin booking."
    : !canPick
      ? "Tài khoản tại máy chỉ đặt sân trong hôm nay. Ngày khác do Admin đặt. Bấm khối để xem chi tiết."
      : canSession
        ? "Bấm từng ô trống để chọn (nhiều sân, nhiều giờ) rồi Đặt sân hoặc Tạo sự kiện · bấm khối để xem chi tiết · Esc bỏ chọn."
        : "Bấm từng ô trống để chọn (nhiều sân, nhiều giờ) rồi Đặt sân · bấm khối để xem chi tiết · Esc bỏ chọn.";

  return (
    // md+: cao đúng phần còn lại dưới header (3.5rem) trừ lề trang ⇒ lưới cuộn bên trong, trang không phải cuộn
    <div className="flex flex-col gap-3 md:h-[calc(100dvh-5.5rem)] lg:h-[calc(100dvh-6rem)]">
      <CalendarToolbar
        date={calendar.date}
        today={today}
        onGoto={(d) => void goto(d)}
        onRecurring={canRecurring ? () => setDialog({ kind: "recurring" }) : null}
        onSearch={findCode}
        unpaidOnly={unpaidOnly}
        unpaidCount={calendar.unpaid_count}
        onUnpaidOnly={setOnlyUnpaid}
      />

      {/* md+: khung lưới co theo chiều cao còn lại (tối thiểu 18rem), cuộn dọc bên trong, hàng giờ dính trên */}
      <div className={cn("transition-opacity md:flex md:min-h-72 md:flex-col motion-reduce:transition-none", loading && "opacity-60")} aria-busy={loading}>
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
      <p className="shrink-0 text-sm text-muted">{footText}</p>

      {selected.size > 0 ? (
        <SelectionBar
          count={selected.size}
          total={total}
          bookReason={bookReason}
          eventReason={canSession ? eventReason : null}
          onClear={clear}
          onBook={openBooking}
          onEvent={openSessionForm}
        />
      ) : null}

      {dialog?.kind === "booking" ? (
        <BookingDialog
          selection={dialog.selection}
          initialBlocks={dialog.blocks}
          calendar={calendar}
          onRefresh={refresh}
          canSession={canSession}
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
      {dialog?.kind === "recurring" ? (
        <RecurringDialog
          calendar={calendar}
          today={today}
          onClose={() => setDialog(null)}
          onChanged={(order) => {
            setHighlight(order);
            refresh();
          }}
          onOpenOrder={(orderCode) => setDialog({ kind: "order", orderCode })}
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
