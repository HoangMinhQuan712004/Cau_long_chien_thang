"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { errorText } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { addDaysIso, formatLongDate, vnDate } from "@/lib/format";
import { BookingDialog, SessionFormDialog } from "./booking-dialogs";
import { ItemFlow } from "./item-flow";
import { getCalendar, searchCode } from "./requests";
import { ResourceTimeline, type RejectReason } from "./resource-timeline";
import { SessionFlow } from "./session-flow";
import type { Calendar, CalendarBlock, Selection } from "./types";
import { inputCls } from "./ui";

// Màn Đặt sân (/admin/dat-san): lịch ngày + các hộp thoại. Dữ liệu đầu lấy ở server; sau đó tải lại ở client:
// mỗi 30 giây khi tab đang hiển thị (NFR-002) và ngay sau mỗi thao tác ghi.

type Dialog =
  | { kind: "booking"; selection: Selection }
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

  function onSelect(sel: Selection) {
    // Quyền đặt quầy / tạo sự kiện của NGÀY đang xem do server quyết (`calendar.can`), không tự suy ra từ ngày hay tháng ở client.
    if (sel.resourceCodes.length === 1 && calendar.can.counter_book) {
      setDialog({ kind: "booking", selection: sel });
    } else if (isAdmin && calendar.can.create_session) {
      setDialog({ kind: "sessionForm", selection: sel });
    } else if (isAdmin) {
      toast("Không đặt được ở ngày này", "Ngày hoặc khung đã qua không chọn được.", "info");
    } else {
      toast("Tài khoản tại máy chỉ đặt từng sân trong hôm nay", "Đặt nhiều sân hoặc ngày khác là Đặt sự kiện, do Admin làm.", "info");
    }
  }

  function onReject(reason: RejectReason) {
    if (reason === "past-day") toast("Ngày đã qua: chỉ xem, không chọn khung mới.", undefined, "info");
    else if (reason === "not-today") toast("Tài khoản tại máy chỉ đặt từng sân trong hôm nay", "Đặt nhiều sân hoặc ngày khác là Đặt sự kiện, do Admin làm.", "info");
    else toast("Vùng chọn có khung đã có người dùng, ngoài giờ mở cửa hoặc đã qua", "Chọn lại các ô trống liền nhau.", "info");
  }

  function onBlockClick(b: CalendarBlock) {
    if (b.type === "booking" && b.code) setDialog({ kind: "item", code: b.code });
    else if (b.type === "session" && b.code) setDialog({ kind: "session", code: b.code });
    else if (b.type === "hold") {
      toast("Khung đang được giữ cho khách đặt online", "Hết 5 phút giữ chỗ mà khách chưa đặt xong thì khung trống lại.", "info");
    }
  }

  async function onSearch(e: React.FormEvent) {
    e.preventDefault();
    const code = query.replace(/\s+/g, "").toUpperCase();
    if (!code) return;
    const res = await searchCode(code);
    if (!res.ok) {
      setSearchError(res.error.code === "E-021" || res.error.status === 404 ? `Không tìm thấy mã ${code}. Kiểm tra lại mã.` : errorText(res.error));
      return;
    }
    setSearchError("");
    const { kind, play_date } = res.data;
    if (play_date !== dateRef.current) await goto(play_date);
    setHighlight(kind === "ticket" ? null : res.data.code);
    setDialog(kind === "session" ? { kind: "session", code: res.data.code } : { kind: "item", code: res.data.code });
  }

  const isToday = calendar.date === today;
  const footText = calendar.is_past
    ? "Ngày đã qua: chỉ xem, không chọn khung mới. Bấm khối để xem Thông tin booking."
    : isAdmin
      ? "Kéo chọn ô trống trên 1 sân hôm nay để Đặt sân · kéo nhiều sân hoặc chọn ngày sau để Đặt sự kiện · bấm khối để xem chi tiết."
      : "Kéo chọn ô trống trên 1 sân trong hôm nay để Đặt sân · bấm khối để xem Thông tin booking hoặc Sự kiện.";

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
            Tìm theo mã booking, sự kiện hoặc vé
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
        <ResourceTimeline
          calendar={calendar}
          selectionMode={isAdmin ? "multi-row" : "single-row-today"}
          unpaidOnly={unpaidOnly}
          highlightCode={highlight}
          disabled={dialog !== null}
          onSelect={onSelect}
          onReject={onReject}
          onBlockClick={onBlockClick}
          onHoldExpired={refresh}
        />
      </div>
      <p className="text-sm text-muted">{footText}</p>

      {dialog?.kind === "booking" ? (
        <BookingDialog
          selection={dialog.selection}
          canSession={isAdmin}
          onClose={() => setDialog(null)}
          onSwitchToSession={() => setDialog({ kind: "sessionForm", selection: dialog.selection })}
          onBooked={(item) => {
            setDialog(null);
            setHighlight(item.code);
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
