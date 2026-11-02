"use client";

import { useEffect, useState } from "react";
import { InvoiceModal, Line } from "@/components/member-area/payment-detail";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { formatLongDate, formatVnd, hhmm } from "@/lib/format";
import type { PayStatus } from "@/components/web-booking/types";
import { getMyBooking, type MyBooking } from "./cell-requests";

// T-023 AC2: hộp thoại "Sân của bạn" mở từ ô đã đặt của chính hội viên trên /hoi-vien/dat-san (popup sự kiện: web-booking/event-dialog.tsx).

const PAY_LABEL: Record<PayStatus, string> = { unpaid: "Chưa thanh toán", paid: "Đã thanh toán", uncollectible: "Không thu được" };

const slotRange = (a: string, b: string) => `${hhmm(a)} – ${hhmm(b)}`;

/** Chạy một lần khi `key` đổi; kết quả `loading | failed | data`. */
function useLoaded<T>(key: string | null, load: (key: string) => Promise<{ ok: true; data: T } | { ok: false }>) {
  const [state, setState] = useState<{ key: string | null; data: T | null; failed: boolean }>({ key: null, data: null, failed: false });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!key) return;
    let stop = false;
    load(key).then((res) => {
      if (!stop) setState({ key, data: res.ok ? res.data : null, failed: !res.ok });
    });
    return () => {
      stop = true;
    };
    // `load` là hàm module cố định
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt]);
  const current = state.key === key;
  return { data: current ? state.data : null, failed: current && state.failed, retry: () => setAttempt((n) => n + 1) };
}

export function MyBookingModal({ orderCode, onClose }: { orderCode: string | null; onClose: () => void }) {
  const { data, failed, retry } = useLoaded<MyBooking>(orderCode, getMyBooking);
  const [invoice, setInvoice] = useState<string | null>(null);
  const paid = data?.items.filter((i) => i.pay_status === "paid") ?? [];
  const hasUnpaid = data?.items.some((i) => i.pay_status === "unpaid") ?? false;

  return (
    <>
      <Modal
        open={orderCode !== null}
        onClose={onClose}
        title="Sân của bạn"
        footer={
          <>
            {paid.map((it) => (
              <Button key={it.code} variant="secondary" onClick={() => setInvoice(it.code)}>
                {paid.length > 1 ? `Xem hóa đơn · ${it.resource_name} ${hhmm(it.start_time)}` : "Xem hóa đơn"}
              </Button>
            ))}
            <Button onClick={onClose}>Đóng</Button>
          </>
        }
      >
        {data ? (
          <>
            <dl className="space-y-2.5 text-sm">
              <Line label="Mã đơn" value={data.order_code} />
              <Line label="Ngày" value={formatLongDate(data.play_date)} />
              {data.items.map((it) => (
                <Line key={it.code} label={it.resource_name} value={`${slotRange(it.start_time, it.end_time)} (${it.hours} giờ)`} />
              ))}
              <Line label="Số tiền" value={formatVnd(data.amount)} />
              <Line label="Thanh toán" value={PAY_LABEL[data.pay_status]} />
              <Line label="Nguồn" value={data.source === "online" ? "Online" : "Tại quầy"} />
            </dl>
            {hasUnpaid ? <Alert variant="info">Thanh toán tại quầy.</Alert> : null}
          </>
        ) : failed ? (
          <div role="alert" className="space-y-3 text-sm">
            <p className="text-danger">Không tải được thông tin đặt sân.</p>
            <Button variant="secondary" onClick={retry}>
              Thử lại
            </Button>
          </div>
        ) : (
          <p className="text-sm text-muted" aria-busy>
            Đang tải…
          </p>
        )}
      </Modal>
      <InvoiceModal code={invoice} onClose={() => setInvoice(null)} />
    </>
  );
}
