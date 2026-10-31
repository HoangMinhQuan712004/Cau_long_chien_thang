"use client";

import { useCallback, useEffect, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatDayMonthYear, formatVnd, hhmm } from "@/lib/format";
import { authFailure } from "./booking-dialogs";
import { getItem, searchCode, sendCollectOrder } from "./requests";
import type { Item, OrderCollect } from "./types";
import { btnCls, btnPrimaryCls, ErrorBanner, resourceLabels, StatusBadge, SummaryBox } from "./ui";

// Một đơn đặt sân (T-019): danh sách khối, mở từng khối, "Thu cả đơn" khi còn ≥ 2 khối chưa thanh toán.

type Props = {
  orderCode: string;
  onClose: () => void;
  onChanged: () => void;
  onOpenItem: (code: string) => void;
};

export function OrderFlow({ orderCode, onClose, onChanged, onOpenItem }: Props) {
  const [items, setItems] = useState<Item[] | null>(null);
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);
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
  const total = items.reduce((n, i) => n + i.payment.amount, 0);
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
          {items.length} khối · Tổng {formatVnd(total)}
          {unpaid.length ? ` · Chưa thu ${formatVnd(unpaidAmount)}` : ""}
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
