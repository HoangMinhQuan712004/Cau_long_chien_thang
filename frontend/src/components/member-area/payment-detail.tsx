"use client";

import { useEffect, useState } from "react";
import { hourRange } from "@/components/play-rooms/utils";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { formatDateTime, formatDayMonthYear, formatVnd } from "@/lib/format";

export type PaymentItem = components["schemas"]["PaymentItem"];

/** Nội dung hóa đơn một khoản đã thanh toán – dùng ở Lịch sử thanh toán và ở ô lịch "Sân của bạn" (T-023 AC2). */
export function PaymentDetailBody({ item }: { item: PaymentItem }) {
  return (
    <dl className="space-y-2.5 text-sm">
      <Line label="Mã" value={item.display_code} />
      <Line label="Nội dung" value={item.title} />
      <Line label="Ngày chơi" value={formatDayMonthYear(item.play_date)} />
      {item.resource_names.length > 0 ? <Line label="Sân" value={item.resource_names.join(", ")} /> : null}
      <Line label="Giờ" value={hourRange(item.start_at, item.end_at)} />
      <Line label="Số tiền" value={formatVnd(item.amount)} />
      {item.cancelled ? <Line label="Trạng thái" value={`Đã hủy${item.refund_amount > 0 ? ` · Đã hoàn ${formatVnd(item.refund_amount)}` : ""}`} /> : null}
      <Line label="Thanh toán lúc" value={formatDateTime(item.paid_at)} />
      <Line label="Hình thức" value={`${item.method} · ${item.channel === "counter" ? "tại quầy" : "online"}`} />
    </dl>
  );
}

export function Line({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[7.5rem_1fr] gap-3">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 font-medium break-words">{value}</dd>
    </div>
  );
}

/** Hóa đơn theo mã con (`GET /member-area/payments/{code}`); mở khi `code` khác null. */
export function InvoiceModal({ code, onClose }: { code: string | null; onClose: () => void }) {
  const [item, setItem] = useState<PaymentItem | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!code) return;
    let stop = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- đặt lại trước mỗi lần tải
    setItem(null);
    setFailed(false);
    api
      .GET("/api/v1/member-area/payments/{code}", { params: { path: { code } } })
      .then(({ data }) => {
        if (stop) return;
        if (data) setItem(data);
        else setFailed(true);
      })
      .catch(() => !stop && setFailed(true));
    return () => {
      stop = true;
    };
  }, [code]);

  return (
    <Modal
      open={code !== null}
      onClose={onClose}
      title="Hóa đơn"
      footer={
        <Button variant="secondary" onClick={onClose}>
          Đóng
        </Button>
      }
    >
      {item ? (
        <PaymentDetailBody item={item} />
      ) : failed ? (
        <p role="alert" className="text-sm text-danger">
          Không tải được hóa đơn. Vui lòng thử lại sau.
        </p>
      ) : (
        <p className="text-sm text-muted" aria-busy>
          Đang tải…
        </p>
      )}
    </Modal>
  );
}
