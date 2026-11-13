"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { mmss } from "./pay-parts";
import { clearPending, paymentPath, savePending, serverNowOf, usePending, type PendingCheckout } from "./pending-checkout";
import { getCheckout } from "./requests";

// T-075 AC6, AC8–AC10: banner "Bạn có lượt đặt đang chờ thanh toán" trên màn Đặt sân (khách / hội viên) và Tổng quan hội viên.
// Kiểm lượt với server MỘT lần khi mở màn: paid / expired / 404 / E-WEB-6 ⇒ xóa; còn chờ ⇒ cập nhật hạn từ server.

/** Giây còn lại tới hạn thanh toán của lượt (giờ server ước tính), cập nhật mỗi giây. */
export function usePendingLeft(p: PendingCheckout | null): number | null {
  const [, setTick] = useState(0);
  const token = p?.token ?? null;
  useEffect(() => {
    if (!token) return;
    const id = setInterval(() => setTick((t) => t + 1), 1000); // render lại mỗi giây để đếm ngược
    return () => clearInterval(id);
  }, [token]);
  if (!p) return null;
  return Math.max(0, Math.ceil((Date.parse(p.expires_at) - serverNowOf(p)) / 1000));
}

export function PendingCheckoutBanner({ member, className = "" }: { member: boolean; className?: string }) {
  const pending = usePending(member);
  const token = pending?.token ?? null;
  const left = usePendingLeft(pending);

  // Một lần cho mỗi lượt: hỏi server trạng thái thật
  useEffect(() => {
    if (!token) return;
    let live = true;
    void getCheckout(token).then((res) => {
      if (!live) return;
      if (res.ok) {
        const c = res.data;
        if (c.status !== "pending") return clearPending(member, token);
        const cur = pending;
        if (cur && cur.token === token) savePending({ ...cur, expires_at: c.expires_at, server_now: c.server_now, order_code: c.order_code });
        return;
      }
      if (res.error.status === 404 || res.error.code === "E-WEB-6") clearPending(member, token);
      // lỗi mạng: giữ banner, lần mở màn sau kiểm lại
    });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- chỉ kiểm một lần cho mỗi token, không theo từng lần đếm giây
  }, [token, member]);

  if (!pending || left == null || left <= 0) return null;
  return (
    // Điện thoại: tiêu đề + đồng hồ một hàng, mã đơn dưới, nút rộng hết; từ sm: nút nằm bên phải cùng hàng
    <div role="status" className={`rounded-xl border border-blk-unpaid-fg/25 bg-blk-unpaid p-3 text-blk-unpaid-fg sm:px-4 ${className}`}>
      <div className="flex flex-col gap-2.5 sm:flex-row sm:items-center sm:gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <p className="min-w-0 text-sm font-bold">Lượt {pending.kind === "event" ? "mua vé" : "đặt sân"} đang chờ thanh toán</p>
            <span className="shrink-0 rounded-full bg-surface/70 px-2.5 py-0.5 text-sm font-bold tabular-nums" aria-label={`còn ${mmss(left)}`}>
              {mmss(left)}
            </span>
          </div>
          <p className="mt-0.5 truncate text-xs">
            Mã <b className="font-mono">{pending.order_code}</b>
          </p>
        </div>
        <Link
          href={paymentPath(pending)}
          className="inline-flex min-h-10 w-full shrink-0 items-center justify-center rounded-lg bg-primary px-4 text-sm font-semibold whitespace-nowrap text-white hover:bg-primary-hover focus-ring sm:w-auto"
        >
          Tiếp tục thanh toán
        </Link>
      </div>
      <p className="mt-2 text-xs opacity-80">
        Đổi máy hoặc trình duyệt? Tra cứu bằng mã đơn + SĐT tại{" "}
        <Link href="/tra-cuu" className="font-semibold underline focus-ring">
          Tra cứu
        </Link>
        .
      </p>
    </div>
  );
}
