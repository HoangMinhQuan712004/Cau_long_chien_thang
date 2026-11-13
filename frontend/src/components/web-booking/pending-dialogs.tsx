"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { Modal } from "@/components/ui/modal";
import { type ApiError, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatLongDate } from "@/lib/format";
import { clearPending as forgetCheckout } from "./pending-checkout";
import { clearPending, payHref, pendingFromApi, type PendingCheckout, type PendingOrder, readPending, savePending, secondsLeft } from "./pending-store";
import { sendCancelCheckout } from "./requests";

// Hộp thoại của luồng đơn chờ thanh toán: xác nhận hủy giữ chỗ, chặn đặt đơn mới khi còn đơn chờ.

/** Giây còn giữ chỗ của đơn, cập nhật mỗi giây. */
function useSecondsLeft(p: PendingOrder): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  return secondsLeft(p, now);
}

/** Phát sau khi hủy giữ chỗ thành công ⇒ màn Đặt sân (kể cả đang giữ ẩn) tải lại lịch để ô "Chờ bạn thanh toán" mất ngay. */
export const HOLD_CANCELLED_EVENT = "wk:hold-cancelled";

const LINK_CTA = "inline-flex h-11 sm:h-10.5 items-center justify-center rounded-lg bg-cta px-4 text-ui font-bold text-cta-fg hover:bg-cta-hover focus-ring";

/** Mã đơn · ngày · từng sân + khung giờ (đơn nhiều sân tách dòng) – dùng chung hộp chặn đơn mới và hộp hủy giữ chỗ. */
function OrderRows({ order, left }: { order: PendingOrder; left?: string }) {
  const ticket = order.title.startsWith("Vé ");
  const slots = order.slots ?? [];
  return (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
      <dt className="text-muted">Mã đơn</dt>
      <dd className="font-semibold">{order.code}</dd>
      <dt className="text-muted">Ngày</dt>
      <dd className="font-medium">{formatLongDate(order.date)}</dd>
      {/* Đơn nhiều sân: mỗi sân một dòng kèm khung giờ riêng */}
      <dt className="text-muted">{ticket ? "Vé" : "Sân"}</dt>
      <dd>
        {slots.length ? (
          <ul className="space-y-1">
            {slots.map((x) => (
              <li key={`${x.name}|${x.start}`}>
                <span className="font-medium">{x.name}</span>{" "}
                <span className="whitespace-nowrap tabular-nums">
                  <span className="text-muted">·</span> <b className="font-semibold">{x.start}–{x.end}</b>
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <>
            <span className="font-medium">{ticket ? order.title.slice(3) : order.title}</span>{" "}
            <span className="whitespace-nowrap tabular-nums">
              <span className="text-muted">·</span> <b className="font-semibold">{order.start}–{order.end}</b>
            </span>
          </>
        )}
      </dd>
      {left ? (
        <>
          <dt className="text-muted">Giữ chỗ còn</dt>
          <dd className="font-bold tabular-nums">{left}</dd>
        </>
      ) : null}
    </dl>
  );
}

/** Xác nhận "Hủy giữ chỗ"; xong thì quên đơn chờ, báo toast rồi gọi `onCancelled`. */
export function CancelHoldDialog({ order, open, onClose, onCancelled }: { order: PendingOrder; open: boolean; onClose: () => void; onCancelled: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function cancel() {
    setBusy(true);
    setError("");
    const res = await write((key) => sendCancelCheckout(key, order.token));
    setBusy(false);
    if (!res.ok) {
      // 409 E-WEB-12: đã có tiền / đã hết giờ ⇒ câu của BE; 404: lượt không còn (hoặc không phải của bạn)
      setError(res.error.message);
      return;
    }
    clearPending(order.token);
    forgetCheckout(order.member, order.token); // banner "đang chờ thanh toán" (T-075) tắt ngay
    toast("Đã hủy giữ chỗ");
    window.dispatchEvent(new Event(HOLD_CANCELLED_EVENT));
    onCancelled();
  }

  return (
    <Modal
      open={open}
      onClose={() => !busy && onClose()}
      title="Hủy giữ chỗ đơn này?"
      footer={
        <>
          <Button variant="secondary" block onClick={onClose} disabled={busy} className="flex-1">
            Giữ chỗ
          </Button>
          <Button variant="danger" block onClick={() => void cancel()} loading={busy} className="flex-1">
            {busy ? "Đang hủy…" : "Hủy giữ chỗ"}
          </Button>
        </>
      }
    >
      <OrderRows order={order} />
      <div className="space-y-2 text-sm">
        <p>{order.title.startsWith("Vé ") ? "Chỗ sẽ được nhả lại cho người khác." : "Khung giờ sẽ được mở lại cho người khác đặt."}</p>
        {error ? (
          <p role="alert" className="rounded-lg bg-danger-soft px-3 py-2 text-danger">
            {error}
          </p>
        ) : null}
      </div>
    </Modal>
  );
}

/** "Bạn còn đơn … chưa thanh toán": chỉ có Thanh toán ngay / Hủy giữ chỗ, không có "vẫn đặt mới". */
function PendingBlockDialog({ order, onClose }: { order: PendingOrder; onClose: () => void }) {
  const left = useSecondsLeft(order);
  const [confirm, setConfirm] = useState(false);
  // Đồng hồ về 0 khi hộp đang mở ⇒ đơn cũ hết giữ chỗ: tự đóng (đang hỏi hủy thì vẫn đóng, không còn gì để hủy)
  useEffect(() => {
    if (left > 0) return;
    clearPending(order.token);
    onClose();
  }, [left, order.token, onClose]);
  const mm = String(Math.floor(left / 60)).padStart(2, "0");
  const ss = String(left % 60).padStart(2, "0");
  return (
    <>
      <Modal
        open={!confirm}
        // Mở hộp xác nhận hủy thì hộp này đóng (sự kiện close) – lúc đó không coi là người dùng tắt, không gỡ cả cụm
        onClose={confirm ? () => {} : onClose}
        title="Bạn còn đơn chưa thanh toán"
        footer={
          <>
            {order.locked ? null : (
              // Cùng cỡ "Thanh toán ngay" (người dùng 13/11: nút cũ cỡ gọn bị chật), hai nút chia đều hàng
              <Button variant="secondary" block onClick={() => setConfirm(true)} className="flex-1">
                Hủy giữ chỗ
              </Button>
            )}
            <Link href={payHref(order)} onClick={onClose} className={cn(LINK_CTA, "flex-1")}>
              Thanh toán ngay
            </Link>
          </>
        }
      >
        {/* Câu hướng dẫn trước, rồi từng dòng nhãn – giá trị (người dùng 13/11: câu liền một đoạn khó đọc) */}
        <p className="text-sm text-muted">Hãy thanh toán hoặc hủy đơn này để đặt đơn mới.</p>
        <OrderRows order={order} left={`${mm}:${ss}`} />
      </Modal>
      <CancelHoldDialog order={order} open={confirm} onClose={() => setConfirm(false)} onCancelled={onClose} />
    </>
  );
}

/**
 * Chặn đặt đơn mới khi còn đơn chờ: `check()` trước khi đi tiếp (true = đã chặn, đang hiện hộp), `fromError(e)` khi tạo đơn
 * bị 409 E-WEB-4 kèm `pending`. Hủy xong thì đóng hộp, khách tiếp tục với các ô đang chọn.
 */
export function usePendingGate(member: boolean) {
  const [order, setOrder] = useState<PendingOrder | null>(null);
  // BE trả 409 kèm đơn cũ đã quá hạn (đồng hồ hai bên lệch) ⇒ không hiện "còn 00:00", báo thử lại
  const [stale, setStale] = useState(false);
  const close = useCallback(() => setOrder(null), []);

  function check(): boolean {
    const p = readPending();
    if (!p) return false;
    // Quá hạn theo giờ server ⇒ coi như không có, quên luôn
    if (p.expired || secondsLeft(p) === 0) {
      clearPending(p.token);
      return false;
    }
    setOrder(p);
    return true;
  }

  function fromError(e: ApiError): boolean {
    if (e.code !== "E-WEB-4" || !e.extra.pending) return false;
    const p = pendingFromApi(e.extra.pending as PendingCheckout, member);
    if (!p) return false;
    if (secondsLeft(p) === 0) {
      clearPending(p.token);
      setStale(true);
      return true;
    }
    savePending(p);
    setOrder(p);
    return true;
  }

  const dialog = (
    <>
      {order ? <PendingBlockDialog key={order.token} order={order} onClose={close} /> : null}
      <Modal open={stale} onClose={() => setStale(false)} title="Đơn cũ vừa hết thời gian giữ chỗ" footer={<Button onClick={() => setStale(false)}>Đã hiểu</Button>}>
        <p className="text-sm">Vui lòng thử lại để đặt đơn mới.</p>
      </Modal>
    </>
  );
  return { check, fromError, dialog };
}
