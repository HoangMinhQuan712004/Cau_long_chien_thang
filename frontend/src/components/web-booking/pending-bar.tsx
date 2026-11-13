"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";
import { mmss } from "./pay-parts";
import { clearPending, payHref, pendingFromApi, pendingLabel, type PendingOrder, readPending, savePending, secondsLeft, usePendingOrder } from "./pending-store";
import { getCheckout, getMemberPending } from "./requests";

// Thanh nhắc "Đang giữ chỗ" trên mọi trang khi máy có đơn chờ thanh toán.
// Máy tính: dải mảnh trong header (dính theo header). Điện thoại: thanh nổi đáy, trên thanh điều hướng khu hội viên.

const POLL_MS = 30_000;
const OVER_MS = 4_000;

/** Giây còn lại, cập nhật mỗi giây; null khi không có đơn. */
export function usePendingLeft(p: PendingOrder | null): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!p) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [p]);
  return p ? secondsLeft(p, now) : null;
}

/** Hỏi lại server (status + giờ server) khi thanh hiện, rồi mỗi 30 giây lúc tab đang mở; hết giờ thì báo vài giây rồi xóa. */
function usePendingSync(p: PendingOrder | null, over: boolean) {
  const token = p?.token;
  useEffect(() => {
    if (!token) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const run = async () => {
      if (timer) clearTimeout(timer);
      const res = await getCheckout(token);
      const cur = readPending();
      if (stop || cur?.token !== token) return;
      if (res.ok) {
        const c = res.data;
        // Đã trả / đã hủy (status "cancelled") ⇒ hết nhắc
        if (c.status !== "pending" && c.status !== "expired") return clearPending(token);
        if (c.status === "expired") return savePending({ ...cur, expired: true });
        const offset = Date.parse(c.server_now) - Date.now();
        // Chỉ ghi khi lệch đáng kể ⇒ không gây vòng cập nhật
        if (c.expires_at !== cur.expiresAt || Math.abs(offset - cur.offset) > 2000) savePending({ ...cur, expiresAt: c.expires_at, offset });
      } else if (res.error.status === 404 || res.error.code === "E-WEB-6") {
        return clearPending(token);
      }
      if (document.visibilityState === "visible") timer = setTimeout(run, POLL_MS);
    };
    const onVisible = () => document.visibilityState === "visible" && void run();
    void run();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [token]);

  useEffect(() => {
    if (!over || !token) return;
    const id = setTimeout(() => clearPending(token), OVER_MS);
    return () => clearTimeout(id);
  }, [over, token]);
}

/** Hội viên: lấy đơn chờ từ server (đặt ở máy khác / localStorage bị xóa vẫn thấy); không còn thì quên đơn hội viên cũ. */
function useMemberPendingSync(enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const run = async () => {
      if (timer) clearTimeout(timer);
      const res = await getMemberPending();
      if (stop) return;
      if (res.ok) {
        const cur = readPending();
        const next = res.data ? pendingFromApi(res.data, true) : null;
        if (next && next.token !== cur?.token) savePending(next);
        else if (!res.data && cur?.member) clearPending(cur.token);
      }
      if (document.visibilityState === "visible") timer = setTimeout(run, POLL_MS);
    };
    const onVisible = () => document.visibilityState === "visible" && void run();
    void run();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [enabled]);
}

type Props = {
  /** strip: dải trong header máy tính; float: thanh nổi điện thoại; both: cả hai (trang khách);
   *  inline: hàng gọn đầu thanh "Bạn đang chọn" ở Đặt sân (điện thoại / máy tính bảng), đi cùng thanh đó */
  part: "strip" | "float" | "both" | "inline";
  /** Chỉ một bản trên trang hỏi server (khu hội viên đặt 2 bản ở 2 chỗ) */
  sync?: boolean;
  /** Khu hội viên: thanh nổi nằm trên thanh điều hướng dưới */
  aboveNav?: boolean;
};

export function PendingBar({ part, sync = true, aboveNav = false }: Props) {
  const p = usePendingOrder();
  const pathname = usePathname();
  const left = usePendingLeft(p);
  const over = !!p && (p.expired === true || left === 0);
  usePendingSync(sync ? p : null, over);
  useMemberPendingSync(sync && aboveNav);
  // Đang ở chính màn QR của đơn ⇒ không nhắc
  if (!p || left == null || pathname === payHref(p)) return null;

  const warn = !over && left <= 60;
  const inline = part === "inline";
  // `gold`: dải máy tính nền vàng cam #e2af30 (cta) – chữ tối cta-fg, vòng mũi tên đổi sang xanh appbar (người dùng 13/11)
  const renderBody = (gold = false) => (
    <div className="min-w-0 flex-1 leading-snug">
      {/* Dòng 1: nhãn + đồng hồ (trái), "Thanh toán →" (phải); dòng 2: sân · giờ chữ nhỏ (người dùng 13/11) */}
      <div className="flex items-center justify-between gap-3">
        <span className={cn("min-w-0", warn || over ? "text-danger" : gold ? "text-cta-fg" : "text-appbar")}>
          {over ? (
            <b>Hết thời gian giữ chỗ</b>
          ) : (
            <>
              <b>{inline ? "Giữ chỗ" : "Đang giữ chỗ"}</b> ·{" "}
              <span className="whitespace-nowrap">
                còn{" "}
                <b role="timer" aria-live="off" className="tabular-nums">
                  {mmss(left)}
                </b>
              </span>
            </>
          )}
        </span>
        {over ? null : <PayLink href={payHref(p)} gold={gold && !warn} />}
      </div>
      <span className={cn("block truncate text-xs", gold && !warn ? "text-cta-fg/80" : "text-appbar/80")}>{pendingLabel(p)}</span>
    </div>
  );
  const body = renderBody();
  // Viền mảnh + bóng xanh (người dùng 13/11). Màu thương hiệu: nền xanh rất nhạt (primary-softer ≈ #f1f6f4, người dùng chọn), chữ xanh appbar (8.5:1; dòng 2 /80 ≈ 5:1),
  // điểm nhấn vàng ở vòng mũi tên. ≤ 60 giây / hết giờ: nền đỏ nhạt, nhãn + đồng hồ đỏ (5.5:1)
  const alert = warn || over;
  const tone = alert ? "bg-danger-soft" : "bg-primary-softer";
  // Viền mảnh + bóng cùng tông (xanh thương hiệu / đỏ khi sắp hết giờ) – người dùng 13/11
  const edge = alert ? "ring-1 ring-danger/30" : "ring-1 ring-primary/30";
  const glow = alert
    ? "shadow-[0_8px_24px_-8px_color-mix(in_srgb,var(--danger)_45%,transparent)]"
    : "shadow-[0_8px_24px_-8px_color-mix(in_srgb,var(--primary)_55%,transparent)]";

  if (inline) {
    return (
      <div role="status" className={cn("rounded-t-[20px] py-1.5 pr-3 pl-4 text-xs sm:rounded-t-2xl lg:hidden", tone, edge)}>
        {body}
      </div>
    );
  }

  return (
    <>
      {part !== "float" ? (
        <div role="status" className={cn("hidden lg:block", alert ? "border-b border-danger/30 bg-danger-soft" : "bg-cta shadow-sm")}>
          <div className="mx-auto flex max-w-6xl items-center px-4 py-1.5 text-sm">{renderBody(true)}</div>
        </div>
      ) : null}
      {part !== "strip" ? (
        <div
          role="status"
          data-pending-float
          className={cn(
            "fixed inset-x-3 z-40 flex items-center rounded-2xl px-4 py-2 text-sm lg:hidden",
            edge,
            glow,
            aboveNav ? "bottom-[calc(4.75rem+env(safe-area-inset-bottom))]" : "bottom-[max(0.75rem,env(safe-area-inset-bottom))]",
            tone,
          )}
        >
          {body}
        </div>
      ) : null}
    </>
  );
}

/** "Thanh toán ⟶": chữ xanh appbar đậm + mũi tên trong vòng tròn vàng cta (chữ cta-fg 7.9:1); vùng chạm ≥ 44px nhờ after:. */
function PayLink({ href, onClick, gold = false }: { href: string; onClick?: () => void; gold?: boolean }) {
  return (
    <Link
      href={href}
      onClick={onClick}
      className={cn(
        "group relative inline-flex shrink-0 items-center gap-1.5 rounded-full font-bold whitespace-nowrap underline-offset-4 hover:underline focus-ring",
        gold ? "text-cta-fg" : "text-appbar",
        "after:absolute after:-inset-x-1 after:-inset-y-3",
      )}
    >
      Thanh toán
      <span
        aria-hidden
        className={cn(
          "grid size-6 shrink-0 place-items-center rounded-full transition-colors motion-reduce:transition-none",
          gold ? "bg-appbar text-surface group-hover:bg-primary-hover" : "bg-cta text-cta-fg group-hover:bg-cta-hover",
        )}
      >
        <svg viewBox="0 0 20 20" className="size-4 motion-safe:animate-nudge-x" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 10h12m-5-5 5 5-5 5" />
        </svg>
      </span>
    </Link>
  );
}
