"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  CalendarIcon,
  CalendarPlusIcon,
  ChartIcon,
  CloseIcon,
  CreditCardIcon,
  IdCardIcon,
  PanelLeftIcon,
  RacketIcon,
  ReceiptIcon,
  SettingsIcon,
  UsersIcon,
} from "@/components/ui/icons";
import { IconButton } from "@/components/ui/icon-button";
import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";
import { can, sortNav } from "./forbidden";

// Thứ tự theo menu_order (sortNav), quyền cần có ở ADMIN_NAV (forbidden.ts); mục nào thiếu quyền thì ẩn. Quyền thật do backend kiểm.
export const NAV_ICONS = {
  baoCao: ChartIcon,
  datSan: CalendarPlusIcon,
  donDatSan: CalendarIcon,
  kyLuc: RacketIcon,
  lichSu: ReceiptIcon,
  hoiVien: UsersIcon,
  san: SettingsIcon,
  thanhToan: CreditCardIcon,
  nhanVien: IdCardIcon,
} as const;

export type SidebarProps = {
  /** Mã quyền của phiên (`perms` từ /admin/auth/me). */
  perms: string[];
  /** Thứ tự menu chung (`menu_order` từ /admin/auth/me). */
  menuOrder: string[];
  name: string;
  roleLabel: string;
  /** Tên khu quản trị theo tên sân (ngăn kéo điện thoại). */
  brand: string;
  t: Dictionary["adminNav"];
  /** Bấm một mục (điện thoại: đóng ngăn kéo). */
  onNavigate?: () => void;
  /** Có ⇒ hiện nút ✕ cạnh logo (ngăn kéo điện thoại). */
  onClose?: () => void;
  /** Thu gọn (máy tính): chỉ còn icon, tên mục qua title + sr-only. */
  isCollapsed: boolean;
  /** Có (máy tính) ⇒ hàng "Phân hệ" đầu menu kèm nút thu gọn / mở rộng. */
  onToggleCollapse?: () => void;
};

/** Nội dung sidebar nền trắng: menu có icon (mục đang mở nền xanh nhạt chữ xanh đậm). Logo + tài khoản nằm trên header (ngăn kéo điện thoại vẫn có logo + ✕). */
export function AdminSidebar({ perms, menuOrder, brand, t, onNavigate, onClose, isCollapsed, onToggleCollapse }: SidebarProps) {
  const pathname = usePathname();
  return (
    <div className={cn(
      `flex h-full flex-col gap-6 bg-surface pt-4 pb-[max(1.25rem,env(safe-area-inset-bottom))]`,
      // Thu gọn: cột 64px, icon canh giữa
      isCollapsed ? "px-2" : "px-4",
    )}>
      {/* Logo + tên chỉ hiện trong ngăn kéo điện thoại; máy tính đã có trên header */}
      {onClose ? (
        <div className="flex items-start justify-between gap-2">
          <Link href="/admin" onClick={onNavigate} className={cn(
            "flex items-center gap-2.5 rounded-lg focus-ring",
            isCollapsed ? "mx-auto" : "pl-2",
          )}>
            <span className={cn("flex flex-col text-sm/normal font-semibold", isCollapsed && `
              sr-only
            `)}>
              <span className="line-clamp-2 wrap-anywhere">{brand}</span>
            </span>
          </Link>
          {onClose ? (
            <IconButton icon={<CloseIcon />} label={t.closeMenu} onClick={onClose} />
          ) : null}
        </div>
      ) : null}

      <nav aria-label={t.navLabel} className="flex flex-col gap-1">
        {onToggleCollapse ? (
          // Tiêu đề nhóm + nút thu gọn; thu gọn thì chỉ còn nút, canh giữa
          <div className={cn("mb-1 flex items-center", isCollapsed ? "justify-center" : `
            justify-between pl-3
          `)}>
            <span className={cn("text-xs font-semibold tracking-wide text-muted uppercase", isCollapsed && `
              sr-only
            `)}>{t.section}</span>
            <IconButton
              icon={<PanelLeftIcon />}
              label={isCollapsed ? t.expand : t.collapse}
              aria-pressed={isCollapsed}
              onClick={onToggleCollapse}
            />
          </div>
        ) : null}
        {sortNav(menuOrder).filter((n) => can(perms, n.perm)).map(({ href, key }) => {
          const Icon = NAV_ICONS[key];
          const isActive = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link
              key={href}
              href={href}
              onClick={onNavigate}
              aria-current={isActive ? "page" : undefined}
              title={isCollapsed ? t.items[key] : undefined}
              className={cn(
                `flex h-11 items-center gap-3 rounded-lg text-sm focus-ring transition-colors`,
                isCollapsed ? "justify-center" : "px-3",
                isActive ? "bg-sidebar-active font-semibold text-sidebar" : `
                  text-muted
                  hover:bg-primary-soft/60 hover:text-primary
                `,
              )}
            >
              {/* Icon nhỏ, cỡ theo rem (phóng to cùng màn lớn) */}
              <Icon className="size-4 shrink-0 xl:size-4.5" />
              <span className={cn("min-w-0 flex-1 truncate", isCollapsed && `sr-only`)}>{t.items[key]}</span>
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
