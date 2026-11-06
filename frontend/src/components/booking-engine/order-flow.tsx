"use client";

import { useCallback, useEffect, useId, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatDayMonthYear, formatTime, formatVnd, hhmm } from "@/lib/format";
import { authFailure } from "./booking-dialogs";
import { getItem, getOrderCancelPreview, searchCode, sendCancelOrder, sendCollectOrder } from "./requests";
import type { CancelPreview, CancelResult, CancelSkipReason, Item, OrderCollect } from "./types";
import { btnCls, btnDangerCls, btnDangerOutlineCls, btnPrimaryCls, ErrorBanner, resourceLabels, StatusBadge, SummaryBox, textareaCls } from "./ui";

// Một đơn đặt sân (T-019): danh sách khối, mở từng khối, "Thu cả đơn" khi còn ≥ 2 khối chưa thanh toán.
// T-051: "Hủy đơn" (chỉ Admin) – xem trước các buổi chưa bắt đầu sẽ hủy rồi hủy một lần; buổi đã chơi giữ nguyên.

type Props = {
  orderCode: string;
  onClose: () => void;
  onChanged: () => void;
  onOpenItem: (code: string) => void;
  /** Mở thẳng bước Hủy đơn (nút "Hủy đơn" ở danh sách Đơn đặt sân). */
  startCancel?: boolean;
};

export function OrderFlow({ orderCode, onClose, onChanged, onOpenItem, startCancel = false }: Props) {
  const [items, setItems] = useState<Item[] | null>(null);
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [cancelling, setCancelling] = useState(startCancel);
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");

  const load = useCallback(async () => {
    const found = await searchCode(orderCode);
    if (!found.ok) return setError(errorText(found.error));
    const codes = found.data.codes?.length ? found.data.codes : [found.data.code];
    const all = await Promise.all(codes.map((c) => getItem(c)));
    const failed = all.find((r) => !r.ok);
    if (failed && !failed.ok) return setError(errorText(failed.error));
    setItems(all.flatMap((r) => (r.ok ? [r.data] : [])));
    setError("");
  }, [orderCode]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải dữ liệu khi mở hộp thoại
    void load();
  }, [load]);

  if (error || !items) {
    return (
      <Modal
        open
        onClose={onClose}
        title={`Đơn ${orderCode}`}
        footer={
          <button type="button" onClick={onClose} className={btnCls}>
            Đóng
          </button>
        }
      >
        {error ? <ErrorBanner>{error}</ErrorBanner> : <p className="py-6 text-center text-sm text-muted">Đang tải…</p>}
      </Modal>
    );
  }

  const unpaid = items.filter((i) => i.payment.payment_status === "unpaid");
  const live = items.filter((i) => i.payment.payment_status !== "cancelled"); // khối đã hủy không tính vào tổng
  const cancelledCount = items.length - live.length;
  const canCancelOrder = items.some((i) => i.actions.includes("cancel")); // chỉ Admin còn buổi chưa bắt đầu (T-051 AC7)
  const total = live.reduce((n, i) => n + i.payment.amount, 0);
  const unpaidAmount = unpaid.reduce((n, i) => n + i.payment.amount, 0);
  const first = items[0];
  // Nút "Thu cả đơn" chỉ khi còn ≥ 2 khối chưa thanh toán (khối lẻ thu ở chi tiết khối)
  const canCollectAll = unpaid.length >= 2 && unpaid.every((i) => i.actions.includes("collect"));

  async function collectAll() {
    if (busy) return;
    setBusy(true);
    setBanner("");
    try {
      const res = await write((key) => sendCollectOrder(key, orderCode));
      if (!res.ok) {
        const e = res.error;
        if (authFailure(e)) return;
        // E-BOOK-4: đã được thu ở máy khác → tải lại
        if (e.code === "E-BOOK-4") {
          toast(errorText(e), undefined, "info");
          setConfirming(false);
          await load();
          onChanged();
          return;
        }
        setBanner(errorText(e));
        return;
      }
      const out = res.data as OrderCollect;
      toast(`Đã thu ${out.order_code}`, `${out.collected.length} khối · ${formatVnd(out.amount)} · Tiền mặt`);
      onChanged();
      onClose();
    } finally {
      setBusy(false);
    }
  }

  if (cancelling) {
    return (
      <CancelOrderDialog
        orderCode={orderCode}
        items={items}
        onBack={() => setCancelling(false)}
        onClose={onClose}
        onChanged={() => {
          void load();
          onChanged();
        }}
        onDone={() => {
          onChanged();
          onClose();
        }}
      />
    );
  }

  // Một hộp, hai bước (danh sách → xác nhận thu): đổi nội dung thay vì mở hộp thứ hai
  // (ẩn hộp thứ nhất sẽ kích hoạt onClose và đóng cả luồng).
  if (confirming) {
    return (
      <Modal
        open
        onClose={onClose}
        title="Thu cả đơn"
        footer={
          <>
            <button type="button" onClick={() => setConfirming(false)} disabled={busy} className={btnCls}>
              Quay lại
            </button>
            <button type="button" onClick={() => void collectAll()} disabled={busy} className={btnPrimaryCls}>
              {busy ? "Đang thu…" : "Xác nhận đã thu tiền mặt"}
            </button>
          </>
        }
      >
        {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
        <SummaryBox>
          <p className="font-semibold">{orderCode}</p>
          <p>
            {unpaid.length} khối chưa thanh toán · <b>{formatVnd(unpaidAmount)}</b>
          </p>
          <p className="text-muted">Các khối đã thanh toán hoặc Không thu được giữ nguyên.</p>
        </SummaryBox>
      </Modal>
    );
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={`Đơn ${orderCode}`}
      size="wide"
      footer={
        <>
          {canCancelOrder ? (
            <button type="button" onClick={() => setCancelling(true)} className={btnDangerOutlineCls}>
              Hủy đơn
            </button>
          ) : null}
          <button type="button" onClick={onClose} className={btnCls}>
            Đóng
          </button>
          {canCollectAll ? (
            <button type="button" onClick={() => setConfirming(true)} className={btnPrimaryCls}>
              Thu cả đơn
            </button>
          ) : null}
        </>
      }
    >
      <SummaryBox>
        <p className="font-semibold">
          {first.customer.name} · {formatDayMonthYear(first.schedule.play_date)}
        </p>
        <p className="text-muted">
          {live.length} khối · Tổng {formatVnd(total)}
          {unpaid.length ? ` · Chưa thu ${formatVnd(unpaidAmount)}` : ""}
          {cancelledCount ? ` · Đã hủy ${cancelledCount} khối` : ""}
        </p>
      </SummaryBox>
      <ul className="divide-y divide-border rounded-lg border border-border">
        {items.map((i) => (
          <li key={i.code} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-3 py-2.5 text-sm">
            <span className="min-w-0">
              <button type="button" onClick={() => onOpenItem(i.code)} className="font-mono text-xs text-primary hover:underline">
                {i.code}
              </button>
              <span className="ml-2">
                {resourceLabels(i.schedule.resource_codes, i.schedule.resource_names)} · {hhmm(i.schedule.start_time)}–{hhmm(i.schedule.end_time)}
              </span>
            </span>
            <span className="flex items-center gap-3">
              <span className="tabular-nums">{formatVnd(i.payment.amount)}</span>
              <StatusBadge status={i.payment.payment_status} />
            </span>
          </li>
        ))}
      </ul>
    </Modal>
  );
}

const SKIP_LABEL: Record<CancelSkipReason, string> = {
  started: "Đã bắt đầu hoặc đã qua, giữ nguyên",
  played: "Đã có trận trong phòng chơi, giữ nguyên",
  cancelled: "Đã hủy trước đó",
  uncollectible: "Không thu được, giữ nguyên",
};

/** Hủy cả đơn (T-051): xem trước từ server, hủy đúng các buổi chưa bắt đầu; server kiểm lại từng buổi lúc hủy. */
function CancelOrderDialog({
  orderCode,
  items,
  onBack,
  onClose,
  onChanged,
  onDone,
}: {
  orderCode: string;
  items: Item[];
  onBack: () => void;
  onClose: () => void;
  onChanged: () => void;
  onDone: () => void;
}) {
  const reasonId = useId();
  const refundId = useId();
  const [preview, setPreview] = useState<CancelPreview | null>(null);
  const [loadError, setLoadError] = useState("");
  const [reason, setReason] = useState("");
  const [refunded, setRefunded] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");

  const loadPreview = useCallback(async () => {
    const res = await getOrderCancelPreview(orderCode);
    if (res.ok) {
      setPreview(res.data);
      setLoadError("");
    } else if (!authFailure(res.error)) setLoadError(errorText(res.error));
  }, [orderCode]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải xem trước khi mở bước Hủy đơn
    void loadPreview();
  }, [loadPreview]);

  const byCode = new Map(items.map((i) => [i.code, i]));
  const kind = items[0]?.customer.kind;
  const refundTotal = preview?.refund_total ?? 0;
  const none = preview ? preview.cancellable.length === 0 : true;
  const errs = {
    reason: !reason.trim() ? "Vui lòng nhập Lý do." : "",
    refund: refundTotal > 0 && !refunded ? "Vui lòng xác nhận việc hoàn tiền cho khách." : "",
  };

  async function confirm() {
    if (!preview || busy) return;
    setSubmitted(true);
    setBanner("");
    if (errs.reason || errs.refund) return;
    setBusy(true);
    try {
      const codes = preview.cancellable.map((c) => c.code);
      const res = await write((key) => sendCancelOrder(key, orderCode, { reason: reason.trim(), refund_confirmed: refunded, codes }));
      if (!res.ok) {
        const e = res.error;
        if (authFailure(e)) return;
        setBanner(errorText(e));
        if (e.code === "E-PAY-5" || e.code === "E-PAY-6" || e.code === "E-PAY-8") await loadPreview(); // dữ liệu đổi: hiện lại danh sách mới
        return;
      }
      const out = res.data as CancelResult;
      toast(`Đã hủy ${out.cancelled.length} buổi · ${orderCode}`, out.refund_total > 0 ? `Đã trừ ${formatVnd(out.refund_total)} khỏi doanh thu` : "Khung đã trống lại");
      if (out.skipped.length) toast(`${out.skipped.length} buổi được giữ nguyên`, "Đã bắt đầu hoặc không hủy được ở thời điểm hủy", "info");
      onChanged();
      onDone();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      size="wide"
      title="Hủy đơn"
      subtitle={orderCode}
      footer={
        <>
          <button type="button" onClick={onBack} disabled={busy} className={btnCls}>
            Quay lại
          </button>
          <button type="button" onClick={() => void confirm()} disabled={busy || none} className={btnDangerCls}>
            {busy ? "Đang hủy…" : preview ? `Xác nhận hủy ${preview.cancellable.length} buổi` : "Xác nhận hủy"}
          </button>
        </>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
      {loadError ? (
        <ErrorBanner>{loadError}</ErrorBanner>
      ) : !preview ? (
        <p className="py-6 text-center text-sm text-muted" role="status">
          Đang tải…
        </p>
      ) : (
        <>
          {preview.cancellable.length > 0 ? (
            <section aria-label="Các buổi sẽ hủy">
              <h3 className="mb-1 text-xs font-semibold tracking-wide text-muted uppercase">Sẽ hủy ({preview.cancellable.length})</h3>
              <ul className="max-h-56 divide-y divide-border overflow-y-auto rounded-lg border border-border">
                {preview.cancellable.map((c) => (
                  <li key={c.code} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-3 py-2 text-sm">
                    <span className="min-w-0">
                      <span className="font-mono text-xs">{c.code}</span>
                      <span className="ml-2 tabular-nums">
                        {formatDayMonthYear(c.play_date)} · {formatTime(c.start_at)}
                      </span>
                      <span className="ml-2 text-muted">{c.resource_name}</span>
                    </span>
                    <span className="flex items-center gap-2">
                      <span className="tabular-nums">{formatVnd(c.amount)}</span>
                      <StatusBadge status={c.payment_status} />
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ) : (
            <ErrorBanner>Đơn này không còn buổi nào hủy được.</ErrorBanner>
          )}
          {preview.skipped.length > 0 ? (
            <section aria-label="Các buổi giữ nguyên">
              <h3 className="mb-1 text-xs font-semibold tracking-wide text-muted uppercase">Giữ nguyên ({preview.skipped.length})</h3>
              <ul className="max-h-40 divide-y divide-border overflow-y-auto rounded-lg border border-border bg-background">
                {preview.skipped.map((k) => {
                  const it = byCode.get(k.code);
                  return (
                    <li key={k.code} className="flex flex-wrap items-center justify-between gap-x-3 px-3 py-1.5 text-sm text-muted">
                      <span>
                        <span className="font-mono text-xs">{k.code}</span>
                        {it ? <span className="ml-2 tabular-nums">{formatDayMonthYear(it.schedule.play_date)}</span> : null}
                      </span>
                      <span>{SKIP_LABEL[k.reason]}</span>
                    </li>
                  );
                })}
              </ul>
            </section>
          ) : null}
          <SummaryBox>
            <p>
              Đã thu: <b>{formatVnd(refundTotal)}</b> · sẽ trừ khỏi doanh thu
            </p>
            <p className="text-muted">Chưa thu: {formatVnd(preview.unpaid_total)} · không ảnh hưởng doanh thu</p>
          </SummaryBox>
          {!none ? (
            <>
              <div>
                <label htmlFor={reasonId} className="mb-1.5 block text-label font-semibold text-muted">
                  Lý do <span className="text-danger">*</span>
                </label>
                <textarea
                  id={reasonId}
                  value={reason}
                  maxLength={200}
                  onChange={(e) => setReason(e.target.value)}
                  aria-invalid={Boolean(submitted && errs.reason) || undefined}
                  placeholder="Khách báo không đến được"
                  className={`${textareaCls} min-h-20`}
                />
                <div className="mt-1 flex text-xs">
                  {submitted && errs.reason ? <span className="text-danger">{errs.reason}</span> : null}
                  <span className="ml-auto text-muted">{reason.length} / 200</span>
                </div>
              </div>
              {refundTotal > 0 ? (
                <div className="space-y-2">
                  <ErrorBanner>
                    Sẽ trừ <b>{formatVnd(refundTotal)}</b> khỏi doanh thu. Hệ thống không tự hoàn tiền, bạn tự trả cho khách.
                  </ErrorBanner>
                  <label htmlFor={refundId} className="flex min-h-11 cursor-pointer items-start gap-2 text-sm">
                    <input id={refundId} type="checkbox" checked={refunded} onChange={(e) => setRefunded(e.target.checked)} aria-invalid={Boolean(submitted && errs.refund) || undefined} className="mt-0.5 size-5 shrink-0 accent-primary" />
                    <span>
                      Tôi đã hoàn / sẽ tự hoàn tiền cho khách <span className="text-danger">*</span>
                      {submitted && errs.refund ? <span className="block text-xs text-danger">{errs.refund}</span> : null}
                    </span>
                  </label>
                </div>
              ) : null}
              <ErrorBanner>Chỉ hủy các buổi chưa bắt đầu; buổi đã chơi giữ nguyên. Đã hủy thì không khôi phục được. Thao tác được ghi vào Lịch sử thao tác.</ErrorBanner>
              <p className="text-xs text-muted">
                {kind === "member"
                  ? "Hội viên có tài khoản sẽ nhận thông báo (không kèm lý do). Nếu khách chưa có tài khoản, hãy tự báo khách."
                  : "Khách không có tài khoản nên không nhận được thông báo nào, hãy tự báo khách."}
              </p>
            </>
          ) : null}
        </>
      )}
    </Modal>
  );
}
