"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Modal } from "@/components/ui/modal";
import { BankBox } from "@/components/web-booking/pay-parts";
import { errorText } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatCountdown, formatVnd } from "@/lib/format";
import { authFailure } from "./booking-dialogs";
import { getCollectQr } from "./requests";
import type { CollectQr } from "./types";
import { btnCls, btnPrimaryCls, ErrorBanner } from "./ui";

// "Thu cả đơn" (T-058): mặc định hiện QR chuyển khoản của đơn (nội dung = mã đơn bỏ gạch), hỏi lại server mỗi 3 giây tới khi
// tiền về, giới hạn 5 phút có đếm ngược như giữ chỗ online (người dùng 10/11), hết giờ thì QR mờ + "Tạo lại mã QR"; nút "Khách trả tiền mặt" chuyển sang bước xác nhận tiền mặt như trước.
// Chưa cài nhận tiền chuyển khoản (E-PAY-9) ⇒ chỉ còn tiền mặt, kèm thông điệp.

const POLL_MS = 3_000;
const LIMIT_SEC = 5 * 60;

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
      // E-BOOK-4: đơn không còn khối chưa thu (đã thu ở máy khác / đã hủy) ⇒ báo và tải lại danh sách.
      // 404 E-BOOK-3 (không có đơn) và lỗi khác: nhánh lỗi chung bên dưới
      if (e.code === "E-BOOK-4") {
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

  // Đếm ngược 5 phút (mỗi giây) và hỏi lại mỗi 3 giây khi đang xem QR; hết giờ thì dừng, chờ "Tạo lại mã QR"
  const [left, setLeft] = useState(LIMIT_SEC);
  const polling = mode === "qr" && qr.state === "ready" && !qr.timedOut;
  useEffect(() => {
    if (!polling) return;
    let lastPoll = Date.now();
    const t = setInterval(() => {
      const remain = LIMIT_SEC - Math.floor((Date.now() - startedAt.current) / 1000);
      setLeft(Math.max(0, remain));
      if (remain <= 0) {
        setQr((q) => (q.state === "ready" ? { ...q, timedOut: true } : q));
        void check(true); // lần hỏi cuối: tiền về sát giờ vẫn được báo
        return;
      }
      if (Date.now() - lastPoll >= POLL_MS) {
        lastPoll = Date.now();
        void check(true);
      }
    }, 1_000);
    return () => clearInterval(t);
  }, [polling, check]);

  const recheck = () => {
    startedAt.current = Date.now();
    setLeft(LIMIT_SEC);
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
              <span className="text-muted">Hết 5 phút chưa thấy tiền về.</span>
              <button type="button" onClick={recheck} className={btnPrimaryCls}>
                Tạo lại mã QR
              </button>
            </div>
          ) : (
            <p role="status" className="flex items-center gap-2 text-sm text-muted">
              <span aria-hidden className="size-2 animate-pulse rounded-full bg-primary motion-reduce:animate-none" />
              Đang chờ tiền về… Còn <b className="text-foreground tabular-nums">{formatCountdown(left)}</b>
            </p>
          )}
        </div>
      ) : null}
    </Modal>
  );
}
