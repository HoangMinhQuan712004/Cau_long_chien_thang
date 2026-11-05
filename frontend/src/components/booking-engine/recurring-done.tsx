"use client";

import { Modal } from "@/components/ui/modal";
import { cn } from "@/lib/cn";
import { formatVnd, hhmm } from "@/lib/format";
import { PriceBreakdown } from "./recurring-price";
import { isoDow, orderSummary } from "./recurring-utils";
import type { Item, RecurringResult } from "./types";
import { btnCls, btnPrimaryCls, btnRowCls, ErrorBanner, raisedFooterCls } from "./ui";

// Kết quả Đặt sân định kỳ (tách từ recurring-dialog.tsx): mã đơn, tiền, Thu cả đơn / Mở đơn.

type Props = {
  done: RecurringResult & { paid: boolean };
  busy: boolean;
  banner: string;
  onClose: () => void;
  onOpenOrder: (orderCode: string) => void;
  onCollect: () => void;
};

export function RecurringDone({ done, busy, banner, onClose, onOpenOrder, onCollect }: Props) {
  const items: Item[] = done.bookings;
  return (
    <Modal
      open
      onClose={onClose}
      title="Đã đặt sân định kỳ"
      footerClassName={raisedFooterCls}
      // Các nút rộng bằng nhau (2 hoặc 3 cột chia đều); mã đơn và số tiền đã ở thân hộp nên nhãn nút gọn
      footer={
        <div className={cn(btnRowCls, done.paid ? "grid-cols-2" : "grid-cols-3")}>
          <button type="button" onClick={onClose} className={btnCls}>
            Đóng
          </button>
          <button type="button" onClick={() => onOpenOrder(done.order_code)} title={`Mở đơn ${done.order_code}`} className={btnCls}>
            Mở đơn
          </button>
          {done.paid ? null : (
            <button type="button" onClick={onCollect} disabled={busy} title={`Thu cả đơn · ${formatVnd(done.total)}`} className={cn(btnPrimaryCls, "whitespace-nowrap")}>
              {busy ? "Đang thu…" : "Thu cả đơn"}
            </button>
          )}
        </div>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
      <p className="text-sm">
        Mã đơn <b className="font-mono">{done.order_code}</b> · {done.bookings.length} buổi
      </p>
      {/* Cùng kiểu "Chi tiết giá" với lúc xem trước; dòng chi tiết không khớp giá gốc của BE ⇒ một dòng tổng gốc */}
      <PriceBreakdown
        lines={items.map((b) => ({ price: b.payment.amount, time: `${hhmm(b.schedule.start_time)}–${hhmm(b.schedule.end_time)}` }))}
        originalAmount={done.original_amount}
        discountPct={done.discount_pct}
        discountAmount={done.discount_amount}
        total={done.total}
        summary={orderSummary(
          items.map((b) => ({ date: b.schedule.play_date, resource_code: b.schedule.resource_codes.join(", ") })),
          [...new Set(items.map((b) => isoDow(b.schedule.play_date)))],
        )}
      />
      <p className={done.paid ? "text-sm font-medium text-primary" : "text-sm text-muted"}>{done.paid ? "Đã thanh toán (tiền mặt)" : "Chưa thanh toán. Thu cả đơn ngay hoặc sau ở màn Đơn định kỳ."}</p>
      <p className="text-xs text-muted">Mỗi buổi hiện trên lịch là một khối mang mã đơn. Chưa có hủy hay đổi buổi.</p>
    </Modal>
  );
}
