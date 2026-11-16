"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";
import { mmss } from "./pay-parts";
import { clearPending, isStale, paymentPath, savePending, serverNowOf, usePending, type PendingCheckout } from "./pending-checkout";
import { pendingFromCheckout, pendingLabel } from "./pending-store";
import { getCheckout, getMemberPending } from "./requests";

// T-075: thẻ "Đang giữ chỗ" khi trình duyệt có lượt chờ thanh toán – vị trí + giao diện theo thẻ người dùng duyệt 13/11:
// mọi trang; máy tính: dải dưới header (dính theo header); điện thoại: thẻ nổi đáy (trên thanh điều hướng khu hội viên);
// Đặt sân lúc đang chọn giờ: hàng gọn dính mép trên thanh "Bạn đang chọn". Mọi khổ cùng một màu vàng cam cta, chữ tối cta-fg,
// vòng mũi tên xanh appbar (người dùng 13/11: bỏ xanh + đỏ ở điện thoại). Ẩn ở chính màn QR của lượt.
// Dữ liệu: kho lượt chờ của T-075 (pending-checkout.ts).

const POLL_MS = 30_000;
const OVER_MS = 4_000;

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

/** Hỏi server khi thẻ hiện rồi mỗi 30 giây lúc tab mở: xong / 404 ⇒ xóa; còn chờ ⇒ cập nhật hạn + nhãn sân · giờ. Hết giờ ⇒ báo vài giây rồi xóa. */
function usePendingSync(p: PendingCheckout | null, over: boolean) {
  const token = p?.token;
  const member = p?.member ?? false;
  useEffect(() => {
    if (!token) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const run = async () => {
      if (timer) clearTimeout(timer);
      const res = await getCheckout(token);
      if (stop) return;
      if (res.ok) {
        const c = res.data;
        if (c.status !== "pending") return clearPending(member, token);
        const info = pendingFromCheckout(c, token, member);
        const label = info ? pendingLabel(info) : undefined;
        const cur = p;
        // Chỉ ghi khi đổi ⇒ không gây vòng cập nhật
        if (cur && cur.token === token && (cur.expires_at !== c.expires_at || cur.label !== label)) {
          savePending({ ...cur, expires_at: c.expires_at, server_now: c.server_now, order_code: c.order_code, label });
        }
      } else if (res.error.status === 404 || res.error.code === "E-WEB-6") {
        return clearPending(member, token);
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- theo lượt (token), không theo từng lần ghi lại hạn / nhãn
  }, [token, member]);

  useEffect(() => {
    if (!over || !token) return;
    const id = setTimeout(() => clearPending(member, token), OVER_MS);
    return () => clearTimeout(id);
  }, [over, token, member]);
}

/** Hội viên: lấy lượt chờ từ server (đặt ở máy khác / localStorage bị xóa vẫn thấy); server không còn ⇒ quên lượt hội viên. */
function useMemberPendingSync(enabled: boolean, cur: PendingCheckout | null) {
  const curToken = cur?.token ?? null;
  useEffect(() => {
    if (!enabled) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const run = async () => {
      if (timer) clearTimeout(timer);
      const res = await getMemberPending();
      if (stop) return;
      if (res.ok) {
        const d = res.data;
        if (d?.pay_token && d.pay_token !== curToken) {
          const hhmm = (t: string) => t.slice(0, 5);
          savePending({
            token: d.pay_token,
            kind: d.kind === "ticket" ? "event" : "court",
            member: true,
            order_code: d.order_code,
            expires_at: d.expires_at,
            server_now: d.server_now,
            label: `${d.kind === "ticket" ? `Vé ${d.title}` : d.title} · ${hhmm(d.start_time)}–${hhmm(d.end_time)}`,
          });
        } else if (!d && curToken) clearPending(true, curToken);
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
  }, [enabled, curToken]);
}

type Props = {
  /** strip: dải dưới header máy tính; float: thẻ nổi điện thoại; both: cả hai (trang khách);
   *  inline: hàng gọn đầu thanh "Bạn đang chọn" ở Đặt sân (điện thoại / máy tính bảng) */
  part: "strip" | "float" | "both" | "inline";
  /** Chỉ một bản trên trang hỏi server (khu hội viên đặt 2 bản ở 2 chỗ) */
  sync?: boolean;
  /** Khu hội viên: thẻ nổi nằm trên thanh điều hướng dưới + lấy lượt chờ của hội viên từ server */
  aboveNav?: boolean;
};

export function PendingCheckoutBanner({ part, sync = true, aboveNav = false }: Props) {
  const memberP = usePending(true);
  const webP = usePending(false);
  const p = memberP ?? webP;
  const pathname = usePathname();
  const left = usePendingLeft(p);
  const over = left === 0;
  usePendingSync(sync ? p : null, over);
  useMemberPendingSync(sync && aboveNav, memberP);
  // Lượt cũ đã quá hạn + ân hạn từ lâu (mở lại trang sau nhiều giờ) ⇒ xóa luôn, không báo "hết giờ"
  const stale = p ? isStale(p) : false;
  useEffect(() => {
    if (p && stale) clearPending(p.member, p.token);
  }, [p, stale]);
  if (!p || left == null || stale || pathname === paymentPath(p)) return null;

  const inline = part === "inline";
  const body = (
    <div className="min-w-0 flex-1 leading-snug">
      {/* Dòng 1: nhãn + đồng hồ (trái), "Thanh toán →" (phải); dòng 2: sân · giờ chữ nhỏ */}
      <div className="flex items-center justify-between gap-3">
        <span className="min-w-0 text-cta-fg">
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
        {over ? null : <PayLink href={paymentPath(p)} />}
      </div>
      <span className="block truncate text-xs text-cta-fg/80">{p.label ?? `Mã ${p.order_code}`}</span>
    </div>
  );

  if (inline) {
    return (
      <div role="status" className="rounded-t-[20px] bg-cta py-1.5 pr-3 pl-4 text-xs sm:rounded-t-2xl lg:hidden">
        {body}
      </div>
    );
  }
  return (
    <>
      {part !== "float" ? (
        <div role="status" className="hidden bg-cta shadow-sm lg:block">
          <div className="mx-auto flex max-w-6xl items-center px-4 py-1.5 text-sm">{body}</div>
        </div>
      ) : null}
      {part !== "strip" ? (
        <div
          role="status"
          data-pending-float
          className={cn(
            "fixed inset-x-3 z-40 flex items-center rounded-2xl bg-cta px-4 py-2 text-sm shadow-lg lg:hidden",
            aboveNav ? "bottom-[calc(4.75rem+env(safe-area-inset-bottom))]" : "bottom-[max(0.75rem,env(safe-area-inset-bottom))]",
          )}
        >
          {body}
        </div>
      ) : null}
    </>
  );
}

/** "Thanh toán ⟶": chữ đậm cta-fg + mũi tên trắng trong vòng tròn xanh appbar (trên nền vàng cam); vùng chạm ≥ 44px nhờ after:. */
function PayLink({ href }: { href: string }) {
  return (
    <Link
      href={href}
      className={cn(
        "group relative inline-flex shrink-0 items-center gap-1.5 rounded-full font-bold whitespace-nowrap underline-offset-4 hover:underline focus-ring",
        "text-cta-fg after:absolute after:-inset-x-1 after:-inset-y-3",
      )}
    >
      Thanh toán
      <span
        aria-hidden
        className={cn(
          "grid size-6 shrink-0 place-items-center rounded-full bg-appbar text-surface transition-colors",
          "group-hover:bg-primary-hover motion-reduce:transition-none",
        )}
      >
        <svg viewBox="0 0 20 20" className="size-4 motion-safe:animate-nudge-x" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 10h12m-5-5 5 5-5 5" />
        </svg>
      </span>
    </Link>
  );
}
