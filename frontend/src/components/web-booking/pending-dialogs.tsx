"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { type ApiError, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatLongDate } from "@/lib/format";
import { usePendingLeft } from "./pending-bar";
import { clearPending, payHref, pendingFromApi, pendingLabel, type PendingCheckout, type PendingOrder, readPending, savePending, secondsLeft } from "./pending-store";
import { sendCancelCheckout } from "./requests";

// Hộp thoại của luồng đơn chờ thanh toán: xác nhận hủy giữ chỗ, chặn đặt đơn mới khi còn đơn chờ, hỏi trước khi rời màn QR.

const LINK_CTA = "inline-flex h-11 items-center justify-center rounded-lg bg-cta px-4 text-sm font-bold text-cta-fg hover:bg-cta-hover focus-ring";

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
    toast("Đã hủy giữ chỗ");
    onCancelled();
  }

  return (
    <Modal
      open={open}
      onClose={() => !busy && onClose()}
      title={`Hủy giữ chỗ ${pendingLabel(order)} · ${formatLongDate(order.date).replace(/\/\d{4}$/, "")}?`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Giữ chỗ
          </Button>
          <Button variant="danger" onClick={() => void cancel()} loading={busy}>
            {busy ? "Đang hủy…" : "Hủy giữ chỗ"}
          </Button>
        </>
      }
    >
      <div className="space-y-2 text-sm">
        <p>{order.title.startsWith("Vé ") ? "Chỗ sẽ được nhả lại cho người khác." : "Khung giờ sẽ được mở lại cho người khác đặt."}</p>
        <p className="text-muted">Nếu bạn đã chuyển khoản, đừng hủy – hệ thống sẽ tự xác nhận trong ít phút.</p>
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
  const left = usePendingLeft(order) ?? 0;
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
        onClose={onClose}
        title="Bạn còn đơn chưa thanh toán"
        footer={
          <>
            {order.locked ? null : (
              <Button variant="secondary" onClick={() => setConfirm(true)} className="h-11 sm:h-11">
                Hủy giữ chỗ
              </Button>
            )}
            <Link href={payHref(order)} onClick={onClose} className={LINK_CTA}>
              Thanh toán ngay
            </Link>
          </>
        }
      >
        <p className="text-sm">
          Bạn còn đơn <b>{order.code}</b> · {pendingLabel(order)} chưa thanh toán (còn{" "}
          <b className="tabular-nums">
            {mm}:{ss}
          </b>
          ). Hãy thanh toán hoặc hủy đơn này để đặt đơn mới.
        </p>
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

/** "Khung giờ vẫn được giữ đến HH:MM. Rời trang?" khi rời màn QR chưa thanh toán. */
export function LeaveDialog({ until, open, onStay, onLeave }: { until: string; open: boolean; onStay: () => void; onLeave: () => void }) {
  return (
    <Modal
      open={open}
      onClose={onStay}
      title="Rời trang thanh toán?"
      footer={
        <>
          <Button variant="secondary" onClick={onLeave}>
            Rời trang
          </Button>
          <Button onClick={onStay}>Ở lại thanh toán</Button>
        </>
      }
    >
      <p className="text-sm">Khung giờ vẫn được giữ đến {until}. Rời trang?</p>
    </Modal>
  );
}
