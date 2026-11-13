"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// `short`: nhãn gọn cho hàng liên kết trên điện thoại (chừa chỗ cho Đăng nhập / Đăng ký)
const NAV = [
  { href: "/dat-san", label: "Đặt sân", short: "Đặt sân" },
  { href: "/tra-cuu", label: "Tra cứu booking", short: "Tra cứu" },
];

/** Liên kết chính của header; gạch chân trang hiện tại. `mobile` = hàng liên kết thu gọn dưới thanh. */
export function SiteNav({ mobile = false }: { mobile?: boolean }) {
  const pathname = usePathname();
  return (
    // Máy tính: mục cao hết header, vạch vàng nằm sát mép dưới header – giống header khu hội viên (desktop-header.tsx)
    <nav aria-label={mobile ? "Chính (di động)" : "Chính"} className={mobile ? "flex gap-5 text-sm sm:hidden" : "hidden gap-1 self-stretch text-sm sm:flex"}>
      {NAV.map((n) => {
        const active = pathname === n.href || pathname.startsWith(`${n.href}/`) || (n.href === "/dat-san" && pathname.startsWith("/thanh-toan"));
        return (
          <Link
            key={n.href}
            href={n.href}
            aria-current={active ? "page" : undefined}
            className={
              mobile
                ? `border-b-4 py-1 whitespace-nowrap focus-ring ${active ? "border-accent font-bold text-surface" : "border-transparent text-surface/75 hover:text-surface"}`
                : `relative flex h-full items-center px-3 whitespace-nowrap focus-ring ${active ? "font-bold text-surface" : "text-surface/75 hover:text-surface"}`
            }
          >
            {mobile ? n.short : n.label}
            {active && !mobile ? <span aria-hidden className="absolute inset-x-3 bottom-0 h-1 rounded-t-full bg-accent" /> : null}
          </Link>
        );
      })}
    </nav>
  );
}

/** Khung đăng nhập dùng chung nhiều màn: chỉ hiện `children` (header web) ở các đường dẫn `paths` (vd /dang-nhap, /dang-ky). */
export function ShowOnPaths({ paths, children }: { paths: string[]; children: React.ReactNode }) {
  const pathname = usePathname();
  return paths.includes(pathname) ? children : null;
}
