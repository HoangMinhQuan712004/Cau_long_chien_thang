"use client";

import Link from "next/link";
import { SiteLogo } from "@/components/site-logo";
import { cn } from "@/lib/cn";

// Header khu hội viên trên máy tính (từ lg) – kiểu "xanh đậm" người dùng chọn 12/11 (học Nike/ESPN): nền xanh đậm liền
// banner, trải hết bề ngang màn; logo ô trắng; mục đang xem chữ trắng đậm + vạch vàng dưới chân.

export type HeaderNav = { href: string; label: string; active: boolean; onClick: (e: React.MouseEvent) => void };
type Props = {
  branding: { name: string; logo_url: string | null };
  homeHref: string;
  onHome: (e: React.MouseEvent) => void;
  nav: HeaderNav[];
  /** Chuông + menu tài khoản (kiểu nền tối). */
  actions: React.ReactNode;
  /** Dải dưới hàng menu, dính theo header (vd thanh nhắc đơn chờ thanh toán). */
  below?: React.ReactNode;
};

export function DesktopHeader({ branding, homeHref, onHome, nav, actions, below }: Props) {
  return (
    <header className="sticky top-0 z-(--z-header) hidden border-b border-surface/10 bg-appbar text-surface lg:block">
      <div className="flex h-16 w-full items-center gap-4 px-6 xl:gap-8">
        <Link href={homeHref} onClick={onHome} className="flex min-w-0 shrink-0 items-center gap-2 font-bold focus-ring">
          <SiteLogo url={branding.logo_url} onDark className="size-8" />
          <span className="truncate" title={branding.name}>
            {branding.name}
          </span>
        </Link>
        <nav aria-label="Khu hội viên" className="flex h-full items-stretch gap-1">
          {nav.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              onClick={n.onClick}
              aria-current={n.active ? "page" : undefined}
              className={cn("relative flex h-full items-center px-3 text-sm whitespace-nowrap focus-ring", n.active ? "font-bold" : "text-surface/75 hover:text-surface")}
            >
              {n.label}
              {n.active ? <span aria-hidden className="absolute inset-x-3 bottom-0 h-1 rounded-t-full bg-accent" /> : null}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">{actions}</div>
      </div>
      {below}
    </header>
  );
}
