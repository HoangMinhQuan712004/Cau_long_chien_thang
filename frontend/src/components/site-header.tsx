import Link from "next/link";
import { Suspense } from "react";
import { SiteNav } from "@/components/site-nav";
import { phoneHref, site } from "@/lib/site";

// Header khách (T-008 AC28): logo, Đặt sân, Tra cứu booking, Hotline. Đăng nhập / Đăng ký tạm ẩn (đăng nhập hội viên làm sau).
export function SiteHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-surface/90 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-4">
        <Link href="/" className="flex items-center gap-2 font-bold text-primary">
          <span aria-hidden className="grid size-8 place-items-center rounded-lg bg-primary text-xs text-primary-fg">
            CL
          </span>
          {site.shortName}
        </Link>
        <Suspense fallback={null}>
          <SiteNav />
        </Suspense>
        <a href={phoneHref} className="ml-auto text-sm hover:text-primary">
          <span className="text-muted">Hotline </span>
          <b>{site.phone}</b>
        </a>
      </div>
      <Suspense fallback={null}>
        <SiteNav mobile />
      </Suspense>
    </header>
  );
}
