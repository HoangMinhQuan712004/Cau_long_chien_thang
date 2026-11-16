"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo } from "react";
import type { GridCell, GridRow } from "@/components/court-grid/court-grid";
import { toast } from "@/lib/feedback";
import { mmss } from "./pay-parts";
import { ownsCell, paymentPath, usePending } from "./pending-checkout";
import { payHref, usePendingOrder } from "./pending-store";
import type { SlotExtra, WebCalendar } from "./types";

// Lưới dùng chung (T-025): dữ liệu lịch khách / hội viên → hàng + ô. Hội viên: ô của mình mở thông tin + hóa đơn, ô người khác
// chỉ báo đã có người đặt (T-023 AC1–AC3). Ô đang giữ chỗ (T-075) đếm ngược; hết hạn là trống ngay + tải lại lịch.

/** Giờ máy lúc vẽ + lệch so với giờ server của lần tải lịch gần nhất. */
export type GridClock = { nowMs: number; offset: number };

type Args = {
  calendar: WebCalendar | null;
  date: string;
  member: boolean;
  clock: GridClock;
  setClock: (fn: (c: GridClock) => GridClock) => void;
  /** Tải lại lịch (im lặng) – khi ô giữ chỗ sớm nhất hết hạn */
  reload: () => void;
  /** Hội viên bấm ô "Sân của bạn" / "Sự kiện": `el` để trả focus khi đóng hộp */
  onOpen: (kind: "mine" | "event", code: string, el: HTMLElement) => void;
};

export function useGridRows({ calendar, date, member, clock, setClock, reload, onOpen }: Args): GridRow[] {
  const router = useRouter();
  const pending = usePending(member);
  // Kho thanh nhắc (pending-store) – dùng khi lịch hội viên báo ô `holding` từ server (đặt ở máy khác vẫn nhận ra)
  const waiting = usePendingOrder();

  // Hạn giữ chỗ của các ô held trên lịch đang xem (giờ server)
  const heldExpiries = useMemo(() => {
    const out: number[] = [];
    for (const r of calendar?.resources ?? []) for (const s of r.slots) if (s.state === "held" && s.expires_at) out.push(Date.parse(s.expires_at));
    return out;
  }, [calendar]);
  // Có ô held ⇒ đếm ngược mỗi giây (nowMs là giờ máy; + clock.offset = giờ server)
  useEffect(() => {
    if (!heldExpiries.length) return;
    const id = setInterval(() => setClock((c) => ({ ...c, nowMs: Date.now() })), 1000);
    return () => clearInterval(id);
  }, [heldExpiries, setClock]);
  // Hết hạn là khung mở lại ngay (người dùng 13/11: bỏ "Sắp mở lại") ⇒ tải lại lịch ngay sau hạn sớm nhất để lấy giá / trạng thái mới
  useEffect(() => {
    if (!heldExpiries.length) return;
    const first = Math.min(...heldExpiries);
    const wait = Math.max(1_000, first + 1_000 - (Date.now() + clock.offset));
    const t = setTimeout(reload, wait);
    return () => clearTimeout(t);
  }, [heldExpiries, clock.offset, reload]);

  return useMemo<GridRow[]>(
    () =>
      (calendar?.resources ?? []).map((r) => {
        const byHour = new Map(r.slots.map((s) => [s.start_hour, s as (typeof r.slots)[number] & SlotExtra]));
        const out: Record<number, GridCell> = {};
        const serverNow = clock.nowMs + clock.offset;
        for (const h of calendar?.columns ?? []) {
          const s = byHour.get(h);
          const key = `${r.code}|${h}`;
          if (!s || s.state === "closed") out[h] = { kind: "off" };
          else if (s.state === "held") {
            // T-075 AC1/AC2/AC7: không chọn được; của mình ⇒ "Chờ bạn thanh toán" (bấm mở lại QR), người khác ⇒ "Đang giữ chỗ"
            const left = s.expires_at ? Math.max(0, Math.ceil((Date.parse(s.expires_at) - serverNow) / 1000)) : 0;
            // Hết giờ ⇒ ô trống ngay (giá có lại sau lần tải lịch ngay sau đó)
            if (left <= 0) {
              out[h] = { kind: "free", price: null };
              continue;
            }
            const local = pending && ownsCell(pending, calendar?.date ?? date, r.code, h) ? paymentPath(pending) : null;
            // Hội viên: server báo ô của mình (`holding`) dù trình duyệt này không lưu lượt
            const fromServer = member && s.holding ? (waiting && waiting.code === s.order_code ? payHref(waiting) : "") : null;
            const mineHref = local ?? fromServer;
            out[h] =
              mineHref != null
                ? {
                    kind: "block",
                    key: `held|mine|${s.order_code ?? pending?.token ?? key}`,
                    tone: "unpaid",
                    lines: ["Chờ bạn thanh toán", <b key="t" className="tabular-nums">{mmss(left)}</b>],
                    aria: `lượt đặt của bạn đang chờ thanh toán, còn ${mmss(left)}, mở lại mã QR`,
                    onClick: () => (mineHref ? router.push(mineHref) : toast("Bạn đang giữ chỗ này, hãy thanh toán để hoàn tất", undefined, "info")),
                  }
                : {
                    kind: "block",
                    key: `held|${s.expires_at ?? key}`,
                    tone: "hold",
                    lines: ["Đang giữ chỗ", <b key="t" className="tabular-nums">{mmss(left)}</b>],
                    aria: `có người đang giữ chỗ, còn ${mmss(left)}`,
                    onClick: () => toast("Khung này đang có người giữ chỗ, sẽ mở lại nếu họ không thanh toán", undefined, "info"),
                  };
          } else if (s.state === "booked") {
            const orderCode = s.order_code;
            out[h] =
              member && s.mine && orderCode
                ? { kind: "block", key: `mine|${orderCode}`, tone: "mine", lines: ["Sân của bạn"], aria: "sân của bạn, xem chi tiết", onClick: (el) => onOpen("mine", orderCode, el) }
                : { kind: "block", key: "booked", tone: "booked", lines: ["Đã đặt"], aria: "đã có người đặt", onClick: () => toast("Khung giờ này đã có người đặt", undefined, "info") };
          } else if (s.state === "event") {
            const eventCode = s.event_code;
            out[h] = {
              kind: "block",
              key: `event|${eventCode ?? key}`,
              tone: "session",
              lines: [s.has_ticket ? "Có vé" : "Sự kiện", <b key="n" className="text-xs">{s.taken}/{s.capacity}</b>],
              aria: `sự kiện ${s.taken ?? 0} trên ${s.capacity ?? 0} người${s.has_ticket ? ", bạn đã có vé" : ""}${eventCode ? ", xem chi tiết" : ""}`,
              ring: Boolean(s.has_ticket),
              onClick: eventCode ? (el) => onOpen("event", eventCode, el) : undefined,
            };
          } else out[h] = { kind: "free", price: s.price ?? null };
        }
        return { code: r.code, name: r.name, cells: out };
      }),
    [calendar, member, clock, pending, waiting, date, router, onOpen],
  );
}
