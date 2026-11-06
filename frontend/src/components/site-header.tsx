import Link from "next/link";
import { Suspense } from "react";
import { HeaderAccount } from "@/components/header-account";
import { SiteLogo } from "@/components/site-logo";
import { SiteNav } from "@/components/site-nav";
import { getBranding } from "@/lib/api/server";
import { phoneHref } from "@/lib/site";

// Header khách: logo, Đặt sân, Tra cứu booking, Hotline, Đăng nhập / Đăng ký (T-013 AC23). Ô "Bạn là hội viên?" vẫn ẩn.
export async function SiteHeader() {
  const { name, phone, logo_url: logoUrl } = await getBranding();
  return (
    <header className="sticky top-0 z-(--z-header) border-b border-border bg-surface/90 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-3 px-4 sm:gap-6">
        {/* /dat-san là trang chính (ADR-012): trỏ thẳng, không qua chuyển hướng "/" */}
        <Link href="/dat-san" className="flex min-w-0 items-center gap-2 font-bold text-primary">
          <SiteLogo url={logoUrl} className="size-8" />
          <span className="truncate" title={name}>{name}</span>
        </Link>
        <Suspense fallback={null}>
          <SiteNav />
        </Suspense>
        <a href={phoneHref(phone)} className="ml-auto shrink-0 text-sm hover:text-primary">
          <span className="hidden text-muted sm:inline">Hotline </span>
          <b>{phone}</b>
        </a>
        <div className="hidden sm:block">
          <Suspense fallback={<div aria-hidden className="h-8 w-40" />}>
            <HeaderAccount />
          </Suspense>
        </div>
      </div>
      <div className="flex items-center justify-between gap-3 px-4 pb-2 sm:hidden">
        <Suspense fallback={null}>
          <SiteNav mobile />
        </Suspense>
        <Suspense fallback={<div aria-hidden className="h-8 w-36" />}>
          <HeaderAccount />
        </Suspense>
      </div>
    </header>
  );
}
