"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Modal } from "@/components/ui/modal";
import { BankBox } from "@/components/web-booking/pay-parts";
import { errorText } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatVnd } from "@/lib/format";
import { authFailure } from "./booking-dialogs";
import { getCollectQr } from "./requests";
import type { CollectQr } from "./types";
import { btnCls, btnPrimaryCls, ErrorBanner } from "./ui";

// "Thu cả đơn" (T-058): mặc định hiện QR chuyển khoản của đơn (nội dung = mã đơn bỏ gạch), hỏi lại server mỗi 3 giây tới khi
// tiền về (tối đa 15 phút, rồi "Kiểm tra lại"); nút "Khách trả tiền mặt" chuyển sang bước xác nhận tiền mặt như trước.
// Chưa cài nhận tiền chuyển khoản (E-PAY-9) ⇒ chỉ còn tiền mặt, kèm thông điệp.

const POLL_MS = 3_000;
const POLL_LIMIT_MS = 15 * 60_000;

type Props = {
  orderCode: string;
  /** Nội dung bước tiền mặt (tóm tắt số khối, số tiền) và thao tác thu tiền mặt sẵn có. */
  cashBody: ReactNode;
  onConfirmCash: () => void;
  busy: boolean;
  /** Lỗi của bước tiền mặt (nơi gọi đặt). */
  banner?: string;
  /** Đóng cả luồng. */
  onClose: () => void;
  /** Có ⇒ nút "Quay lại" (vd về danh sách khối của đơn) thay cho "Đóng". */
  onBack?: () => void;
  /** Tiền về / đơn đã thu xong ⇒ nơi gọi tải lại và đóng. */
  onPaid: () => void;
};

type Qr =
  | { state: "loading" }
  | { state: "ready"; data: CollectQr; timedOut: boolean }
  | { state: "unavailable"; message: string }
  | { state: "error"; message: string };

export function CollectQrDialog({ orderCode, cashBody, onConfirmCash, busy, banner, onClose, onBack, onPaid }: Props) {
  const [mode, setMode] = useState<"qr" | "cash">("qr");
  const [qr, setQr] = useState<Qr>({ state: "loading" });
  const startedAt = useRef(0);
  const done = useRef(false);
  const onPaidRef = useRef(onPaid);
  useEffect(() => {
    onPaidRef.current = onPaid;
  }, [onPaid]);

  const finish = useCallback((data: CollectQr) => {
    if (done.current) return;
    done.current = true;
    toast("Đã nhận tiền chuyển khoản", `${data.order_code} · ${formatVnd(data.amount)}`);
    onPaidRef.current();
  }, []);

  /** Một lần hỏi server. `silent`: lỗi mạng khi đang hỏi định kỳ thì giữ QR, lần sau hỏi tiếp. */
  const check = useCallback(
    async (silent: boolean) => {
      const res = await getCollectQr(orderCode);
      if (done.current) return;
      if (res.ok) {
        if (res.data.status === "paid") return finish(res.data);
        setQr((q) => ({ state: "ready", data: res.data, timedOut: q.state === "ready" ? q.timedOut : false }));
        return;
      }
      const e = res.error;
      if (authFailure(e)) return onClose();
      if (e.code === "E-PAY-9") return setQr({ state: "unavailable", message: errorText(e) });
      // E-PAY-6: đơn không còn khoản chưa thu (đã thu ở máy khác / đã hủy) ⇒ báo và tải lại danh sách
      if (e.code === "E-PAY-6") {
        done.current = true;
        toast(errorText(e), orderCode, "info");
        onPaidRef.current();
        return;
      }
      if (!silent) setQr({ state: "error", message: errorText(e) });
    },
    [orderCode, finish, onClose],
  );

  // Lần đầu mở
  useEffect(() => {
    startedAt.current = Date.now();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải QR khi mở popup
    void check(false);
  }, [check]);

  // Hỏi lại mỗi 3 giây khi đang xem QR; quá 15 phút thì dừng, chờ "Kiểm tra lại"
  const polling = mode === "qr" && qr.state === "ready" && !qr.timedOut;
  useEffect(() => {
    if (!polling) return;
    const t = setInterval(() => {
      if (Date.now() - startedAt.current > POLL_LIMIT_MS) {
        setQr((q) => (q.state === "ready" ? { ...q, timedOut: true } : q));
        return;
      }
      void check(true);
    }, POLL_MS);
    return () => clearInterval(t);
  }, [polling, check]);

  const recheck = () => {
    startedAt.current = Date.now();
    setQr((q) => (q.state === "ready" ? { ...q, timedOut: false } : { state: "loading" }));
    void check(false);
  };

  const closeBtn = onBack ? (
    <button type="button" onClick={onBack} disabled={busy} className={btnCls}>
      Quay lại
    </button>
  ) : (
    <button type="button" onClick={onClose} disabled={busy} className={btnCls}>
      Đóng
    </button>
  );

  // Bước tiền mặt (chọn "Khách trả tiền mặt", hoặc chưa cài nhận chuyển khoản)
  if (mode === "cash" || qr.state === "unavailable") {
    const qrOff = qr.state === "unavailable";
    return (
      <Modal
        open
        onClose={onClose}
        title="Thu cả đơn · Tiền mặt"
        footer={
          <>
            {qrOff ? (
              closeBtn
            ) : (
              <button type="button" onClick={() => setMode("qr")} disabled={busy} className={btnCls}>
                Quay lại mã QR
              </button>
            )}
            <button type="button" onClick={onConfirmCash} disabled={busy} className={btnPrimaryCls}>
              {busy ? "Đang thu…" : "Xác nhận đã thu tiền mặt"}
            </button>
          </>
        }
      >
        {qrOff ? (
          <p role="status" className="rounded-md bg-blk-unpaid p-3 text-sm text-blk-unpaid-fg">
            {qr.message}
          </p>
        ) : null}
        {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
        {cashBody}
      </Modal>
    );
  }

  return (
    <Modal
      open
      onClose={onClose}
      title="Thu cả đơn · Chuyển khoản"
      size="wide"
      footer={
        <>
          {closeBtn}
          <button type="button" onClick={() => setMode("cash")} disabled={busy} className={btnCls}>
            Khách trả tiền mặt
          </button>
        </>
      }
    >
      {qr.state === "loading" ? <p className="py-10 text-center text-sm text-muted">Đang tạo mã QR…</p> : null}
      {qr.state === "error" ? (
        <div className="space-y-3">
          <ErrorBanner>{qr.message}</ErrorBanner>
          <button type="button" onClick={recheck} className={btnCls}>
            Thử lại
          </button>
        </div>
      ) : null}
      {qr.state === "ready" ? (
        <div className="space-y-4">
          <p className="text-sm">
            Khách quét mã để chuyển <b>{formatVnd(qr.data.amount)}</b> cho đơn <b className="font-mono">{qr.data.order_code}</b> ({qr.data.blocks} khối chưa thu).
            Tiền về đúng số thì cả đơn tự thành Đã thanh toán.
          </p>
          <BankBox bank={qr.data.bank} amount={qr.data.amount} payRef={qr.data.pay_ref} dim={qr.timedOut} />
          {qr.timedOut ? (
            <div className="flex flex-wrap items-center gap-3 rounded-md bg-background p-3 text-sm">
              <span className="text-muted">Đã chờ 15 phút chưa thấy tiền về.</span>
              <button type="button" onClick={recheck} className={btnPrimaryCls}>
                Kiểm tra lại
              </button>
            </div>
          ) : (
            <p role="status" className="flex items-center gap-2 text-sm text-muted">
              <span aria-hidden className="size-2 animate-pulse rounded-full bg-primary motion-reduce:animate-none" />
              Đang chờ tiền về… Màn này tự cập nhật.
            </p>
          )}
          <p className="text-xs text-muted">Chuyển thiếu hoặc thừa: đơn giữ Chưa thanh toán, khoản tiền nằm ở &quot;Tiền về cần xử lý&quot; để hoàn.</p>
        </div>
      ) : null}
    </Modal>
  );
}
