import Link from "next/link";
import { site } from "@/lib/site";

const NAV = [
  { href: "/dat-san", label: "Đặt sân" },
  { href: "/bang-gia", label: "Bảng giá" },
  { href: "/tin-tuc", label: "Tin tức" },
];

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-20 border-b border-border bg-surface/90 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-4">
        <Link href="/" className="flex items-center gap-2 font-bold text-primary">
          <span aria-hidden className="inline-block size-3 rounded-full bg-accent" />
          {site.shortName}
        </Link>
        <nav aria-label="Chính" className="hidden gap-5 text-sm font-medium sm:flex">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} className="hover:text-primary">
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3 text-sm">
          <Link href="/tai-khoan" className="hover:text-primary">
            Tài khoản
          </Link>
          <Link
            href="/dat-san"
            className="rounded-md bg-primary px-3 py-2 font-medium text-primary-fg"
          >
            Đặt sân ngay
          </Link>
        </div>
      </div>
      <nav aria-label="Chính (di động)" className="flex gap-5 px-4 pb-2 text-sm sm:hidden">
        {NAV.map((n) => (
          <Link key={n.href} href={n.href}>
            {n.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
