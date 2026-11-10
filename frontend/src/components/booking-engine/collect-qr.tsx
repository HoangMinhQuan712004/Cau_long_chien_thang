"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Modal } from "@/components/ui/modal";
import { BankBox } from "@/components/web-booking/pay-parts";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatCountdown, formatVnd } from "@/lib/format";
import { authFailure } from "./booking-dialogs";
import { getCollectQr, getItemCollectQr, getOrderItems, sendOrderUncollectible } from "./requests";
import type { CollectQr, OrderUncollectible } from "./types";
import { btnCls, btnDangerCls, btnDangerOutlineCls, btnPrimaryCls, ErrorBanner, textareaCls } from "./ui";

// "Thu cả đơn" (T-058): mặc định hiện QR chuyển khoản của đơn (nội dung = mã đơn bỏ gạch), hỏi lại server mỗi 3 giây tới khi
// tiền về, giới hạn 5 phút có đếm ngược như giữ chỗ online (người dùng 10/11), hết giờ thì QR mờ + "Tạo lại mã QR"; nút "Khách trả tiền mặt" chuyển sang bước xác nhận tiền mặt như trước.
// Chưa cài nhận tiền chuyển khoản (E-PAY-9) ⇒ chỉ còn tiền mặt, kèm thông điệp.
// T-064: nút "Không thu được" ở cả bước QR và tiền mặt: đánh dấu các buổi ĐÃ TỚI GIỜ của đơn (buổi sau giữ Chưa thanh toán),
// hỏi xác nhận kèm lý do (không bắt buộc); xong thì dừng hỏi QR và đóng popup.
const NOT_STARTED = "Chưa có buổi nào tới giờ chơi, chưa thể đánh dấu Không thu được.";
const NOT_STARTED_ITEM = "Buổi này chưa tới giờ chơi, chưa thể đánh dấu Không thu được.";
const REASON_MAX = 200; // cột DB (BE: 201+ ký tự ⇒ 422)

const POLL_MS = 3_000;
const LIMIT_SEC = 5 * 60;

type Props = {
  orderCode: string;
  /**
   * T-065: thu MỘT buổi (mã con) thay vì cả đơn. QR riêng của khối (nội dung = mã con bỏ gạch); nút "Không thu được" do nơi
   * gọi lo (`itemBad`, theo quy tắc từng buổi sẵn có).
   */
  item?: { code: string; bad: { enabled: boolean; onClick: () => void } };
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
  /** Đơn xong việc (tiền về / đã thu ở máy khác / vừa đánh dấu Không thu được) ⇒ nơi gọi tải lại và đóng. */
  onPaid: () => void;
};

type Qr =
  | { state: "loading" }
  | { state: "ready"; data: CollectQr; timedOut: boolean }
  | { state: "unavailable"; message: string }
  | { state: "error"; message: string };

// Khối không còn Chưa thanh toán khi hỏi QR từng buổi (đã thu / hủy / Không thu được ở máy khác) ⇒ coi như xong, tải lại
const ITEM_DONE = new Set(["E-BOOK-4", "E-PAY-6", "E-012"]);

export function CollectQrDialog({ orderCode, item, cashBody, onConfirmCash, busy, banner, onClose, onBack, onPaid }: Props) {
  const itemCode = item?.code;
  const label = itemCode ? "Thu tiền" : "Thu cả đơn";
  const [mode, setMode] = useState<"qr" | "cash" | "bad">("qr");
  // Buổi đánh dấu được (chưa thu, đã tới giờ ⇒ BE cho thao tác "uncollectible") và buổi chưa tới giờ; null = đang tải / lỗi
  const [bad, setBad] = useState<{ count: number; amount: number; later: number } | null>(null);
  const [reason, setReason] = useState("");
  const [badBusy, setBadBusy] = useState(false);
  const [badError, setBadError] = useState("");
  const [back, setBack] = useState<"qr" | "cash">("qr");
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
      const res = itemCode ? await getItemCollectQr(itemCode) : await getCollectQr(orderCode);
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
      if (itemCode ? ITEM_DONE.has(e.code ?? "") : e.code === "E-BOOK-4") {
        done.current = true;
        toast(errorText(e), itemCode ?? orderCode, "info");
        onPaidRef.current();
        return;
      }
      if (!silent) setQr({ state: "error", message: errorText(e) });
    },
    [orderCode, itemCode, finish, onClose],
  );

  // Lần đầu mở
  useEffect(() => {
    startedAt.current = Date.now();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải QR khi mở popup
    void check(false);
  }, [check]);

  // Các buổi của đơn: đếm buổi đánh dấu Không thu được được (T-064)
  useEffect(() => {
    if (itemCode) return; // thu một buổi: nơi gọi tự quyết nút Không thu được
    let live = true;
    void getOrderItems(orderCode).then((res) => {
      if (!live || !res.ok) return;
      const unpaid = res.data.filter((i) => i.payment.payment_status === "unpaid");
      const ready = unpaid.filter((i) => i.actions.includes("uncollectible"));
      setBad({ count: ready.length, amount: ready.reduce((n, i) => n + i.payment.amount, 0), later: unpaid.length - ready.length });
    });
    return () => {
      live = false;
    };
  }, [orderCode, itemCode]);

  async function markUncollectible() {
    if (badBusy) return;
    setBadBusy(true);
    setBadError("");
    try {
      const res = await write((key) => sendOrderUncollectible(key, orderCode, reason.trim()));
      if (!res.ok) {
        const e = res.error;
        if (authFailure(e)) return onClose();
        // Máy khác vừa thu / đánh dấu: hết khối chưa thu (E-BOOK-4) hoặc chỉ còn buổi chưa tới giờ (E-PAY-1) ⇒ báo và tải lại
        if (e.code === "E-BOOK-4" || e.code === "E-PAY-1") {
          done.current = true;
          toast(errorText(e), orderCode, "info");
          onPaidRef.current();
          return;
        }
        setBadError(errorText(e));
        return;
      }
      const out = res.data as OrderUncollectible;
      done.current = true; // dừng hỏi QR
      toast(
        out.remaining_unpaid.length
          ? `Đã đánh dấu ${out.marked.length} buổi; còn ${out.remaining_unpaid.length} buổi chưa tới giờ`
          : `Đã đánh dấu Không thu được ${out.marked.length} buổi`,
        out.order_code,
      );
      onPaidRef.current();
    } finally {
      setBadBusy(false);
    }
  }

  const openBad = (from: "qr" | "cash") => {
    setBack(from);
    setBadError("");
    setMode("bad");
  };
  // Chưa tới giờ: cả đơn = không buổi nào đánh dấu được; một buổi = BE không cho thao tác "uncollectible"
  const notStarted = item ? !item.bad.enabled : bad?.count === 0;
  const badDisabled = busy || (item ? !item.bad.enabled : !bad || bad.count === 0);
  // Nút "Không thu được" (trái chân hộp) + dòng lý do khi chưa tới giờ
  const badBtn = (from: "qr" | "cash") => (
    <button
      type="button"
      onClick={() => (item ? item.bad.onClick() : openBad(from))}
      disabled={badDisabled}
      title={notStarted ? (item ? NOT_STARTED_ITEM : NOT_STARTED) : undefined}
      className={btnDangerOutlineCls}
    >
      Không thu được
    </button>
  );
  const badHint = notStarted ? <p className="text-xs text-muted">{item ? NOT_STARTED_ITEM : NOT_STARTED}</p> : null;

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

  // Xác nhận Không thu được (T-064)
  if (mode === "bad" && bad) {
    return (
      <Modal
        open
        onClose={onClose}
        title="Không thu được"
        footer={
          <>
            <button type="button" onClick={() => setMode(back)} disabled={badBusy} className={btnCls}>
              Quay lại
            </button>
            <button type="button" onClick={() => void markUncollectible()} disabled={badBusy} className={btnDangerCls}>
              {badBusy ? "Đang lưu…" : "Xác nhận Không thu được"}
            </button>
          </>
        }
      >
        {badError ? <ErrorBanner>{badError}</ErrorBanner> : null}
        <p className="text-sm">
          Đánh dấu <b>{bad.count} buổi</b> đã tới giờ của đơn <b className="font-mono">{orderCode}</b>, tổng <b>{formatVnd(bad.amount)}</b>, là Không thu được.
        </p>
        {bad.later ? <p className="text-sm text-muted">Còn {bad.later} buổi chưa tới giờ giữ Chưa thanh toán.</p> : null}
        <label className="block text-sm">
          <span className="mb-1 block font-medium">
            Lý do <span className="font-normal text-muted">(không bắt buộc)</span>
          </span>
          <textarea value={reason} maxLength={REASON_MAX} rows={3} onChange={(e) => setReason(e.target.value)} className={textareaCls} />
        </label>
      </Modal>
    );
  }

  // Bước tiền mặt (chọn "Khách trả tiền mặt", hoặc chưa cài nhận chuyển khoản)
  if (mode === "cash" || qr.state === "unavailable") {
    const qrOff = qr.state === "unavailable";
    return (
      <Modal
        open
        onClose={onClose}
        title={`${label} · Tiền mặt`}
        footer={
          <>
            {badBtn("cash")}
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
        {badHint}
      </Modal>
    );
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={`${label} · Chuyển khoản`}
      size="wide"
      footer={
        <>
          {badBtn("qr")}
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
            {itemCode ? (
              <>
                Khách quét mã để chuyển <b>{formatVnd(qr.data.amount)}</b> cho buổi <b className="font-mono">{qr.data.order_code}</b>. Tiền về đúng số thì buổi
                này tự thành Đã thanh toán; các buổi khác của đơn giữ nguyên.
              </>
            ) : (
              <>
                Khách quét mã để chuyển <b>{formatVnd(qr.data.amount)}</b> cho đơn <b className="font-mono">{qr.data.order_code}</b> ({qr.data.blocks} khối chưa
                thu). Tiền về đúng số thì cả đơn tự thành Đã thanh toán.
              </>
            )}
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
      {badHint}
    </Modal>
  );
}
