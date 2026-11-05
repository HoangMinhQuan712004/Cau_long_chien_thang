"use client";

import Link from "next/link";
import { useState } from "react";
import { Drawer } from "@/components/ui/drawer";
import { IconButton } from "@/components/ui/icon-button";
import { MenuIcon } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import { AccountMenu } from "./account-menu";
import { FORBIDDEN_REPORT_VALUE, FORBIDDEN_VALUE } from "./forbidden";
import { ForbiddenToast } from "./forbidden-toast";
import { AdminSidebar, type SidebarProps } from "./admin-sidebar";
import { useSidebarCollapsed } from "./use-sidebar-collapsed";

type Props = Omit<SidebarProps, "onNavigate" | "onClose" | "isCollapsed" | "onToggleCollapse"> & {
  /** Thu gọn menu lúc đầu (cookie, server đọc). */
  initialCollapsed: boolean;
  children: React.ReactNode;
};

/**
 * Khung quản trị: header trắng rộng hết màn, dính trên cùng (nút menu, logo + tên, tài khoản + Đăng xuất).
 * Máy tính: sidebar dính trái, thu gọn được thành cột icon (nhớ lựa chọn); điện thoại: nút ☰ mở ngăn kéo menu.
 */
export function AdminShell({ children, initialCollapsed, ...sidebar }: Props) {
  const { t } = sidebar;
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [isCollapsed, toggleCollapsed] = useSidebarCollapsed(initialCollapsed);
  const close = () => setIsMenuOpen(false);

  return (
    <div className="flex min-h-full flex-1 flex-col">
      <ForbiddenToast messages={{ [FORBIDDEN_VALUE]: t.forbidden, [FORBIDDEN_REPORT_VALUE]: t.forbiddenReport }} />
      {/* Header xanh đậm rộng hết màn, dính trên cùng: nút menu, logo + tên, tài khoản */}
      <header className={cn(`
        sticky top-0 z-20 flex h-14 shrink-0 items-center gap-2 bg-sidebar px-3
        pt-[env(safe-area-inset-top)] text-sidebar-fg
        lg:gap-3 lg:px-4
      `)}>
        {/* Điện thoại: mở ngăn kéo menu (máy tính thu gọn menu ở đầu sidebar) */}
        <IconButton
          icon={<MenuIcon />}
          label={t.openMenu}
          variant="inverse"
          aria-expanded={isMenuOpen}
          onClick={() => setIsMenuOpen(true)}
          className="lg:hidden"
        />
        <Link href="/admin" className={cn(`
          flex min-w-0 items-center gap-2 rounded-lg pr-1 focus-ring-inverse
        `)}>
          <span className="truncate text-sm font-bold">{t.brand}</span>
        </Link>
        <div className="ml-auto shrink-0">
          <AccountMenu perms={sidebar.perms} name={sidebar.name} roleLabel={sidebar.roleLabel} t={t} />
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* Sidebar nền trắng, dính dưới header */}
        <aside className={cn(
          `
            sticky top-14 hidden h-[calc(100dvh-3.5rem)] shrink-0 overflow-y-auto transition-[width]
            duration-200
            motion-reduce:transition-none
            lg:block
          `,
          "border-r",
          isCollapsed ? "w-16" : "w-60",
        )}>
          <AdminSidebar {...sidebar} isCollapsed={isCollapsed} onToggleCollapse={toggleCollapsed} />
        </aside>

        {/* --sticky-top: phần dính trong trang (vd tiêu đề bảng) nằm dưới header cao 3.5rem */}
        <main className="min-w-0 flex-1 p-4 [--sticky-top:3.5rem] lg:px-6 lg:py-5">{children}</main>
      </div>

      <Drawer open={isMenuOpen} onClose={close} side="left" label={t.navLabel} closeLabel={t.closeMenu}>
        <AdminSidebar {...sidebar} isCollapsed={false} onNavigate={close} onClose={close} />
      </Drawer>
    </div>
  );
}
