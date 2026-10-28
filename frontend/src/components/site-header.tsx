import Link from "next/link";
import { Suspense } from "react";
import { SiteNav } from "@/components/site-nav";
import { phoneHref, site } from "@/lib/site";

// Header khách (T-008 AC28): logo, Đặt sân, Tra cứu booking, Hotline. Đăng nhập / Đăng ký tạm ẩn (đăng nhập hội viên làm sau).
export function SiteHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-surface/90 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-3 px-4 sm:gap-6">
        <Link href="/" className="flex min-w-0 items-center gap-2 font-bold text-primary">
          <span aria-hidden className="grid size-8 place-items-center rounded-lg bg-primary text-xs text-primary-fg">
            CL
          </span>
          {site.shortName}
        </Link>
        <Suspense fallback={null}>
          <SiteNav />
        </Suspense>
        <a href={phoneHref} className="ml-auto shrink-0 text-sm hover:text-primary">
          <span className="hidden text-muted sm:inline">Hotline </span>
          <b>{site.phone}</b>
        </a>
      </div>
      <Suspense fallback={null}>
        <SiteNav mobile />
      </Suspense>
    </header>
  );
}
