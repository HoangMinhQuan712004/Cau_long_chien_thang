"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/dat-san", label: "Đặt sân" },
  { href: "/tra-cuu", label: "Tra cứu booking" },
];

/** Liên kết chính của header; gạch chân trang hiện tại. `mobile` = hàng liên kết thu gọn dưới thanh. */
export function SiteNav({ mobile = false }: { mobile?: boolean }) {
  const pathname = usePathname();
  return (
    <nav aria-label={mobile ? "Chính (di động)" : "Chính"} className={mobile ? "flex gap-5 px-4 pb-2 text-sm sm:hidden" : "hidden gap-6 text-sm font-medium sm:flex"}>
      {NAV.map((n) => {
        const active = pathname === n.href || pathname.startsWith(`${n.href}/`) || (n.href === "/dat-san" && pathname.startsWith("/thanh-toan"));
        return (
          <Link
            key={n.href}
            href={n.href}
            aria-current={active ? "page" : undefined}
            className={`border-b-2 py-1 ${active ? "border-primary text-primary" : "border-transparent hover:text-primary"}`}
          >
            {n.label}
          </Link>
        );
      })}
    </nav>
  );
}
