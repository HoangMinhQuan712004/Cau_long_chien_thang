"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { LogoutButton } from "@/components/logout-button";
import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";
import { ChevronDownIcon, HistoryIcon, LogOutIcon } from "@/components/ui/icons";

type Props = {
  role: "admin" | "staff";
  name: string;
  roleLabel: string;
  t: Dictionary["adminNav"];
};

// "Nguyễn Văn An" ⇒ "VA"; "Admin" ⇒ "AD"
function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const letters = words.length > 1 ? words.slice(-2).map((w) => w[0]) : [...(words[0] ?? "?")].slice(0, 2);
  return letters.join("").toLocaleUpperCase("vi");
}

/** Tài khoản trên header: bấm mở menu nhỏ (tên, vai trò, Lịch sử thao tác – chỉ Admin, Đăng xuất); đóng bằng Esc hoặc bấm ra ngoài. */
export function AccountMenu({ role, name, roleLabel, t }: Props) {
  const [isOpen, setIsOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!isOpen) return;
    const onPointer = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setIsOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault(); // trong ngăn kéo điện thoại: chỉ đóng menu, không đóng cả ngăn kéo
      setIsOpen(false);
      buttonRef.current?.focus();
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [isOpen]);

  return (
    <div ref={rootRef} className="relative">
      {/* Nút tài khoản trên header: chữ viết tắt; từ sm kèm tên + vai trò */}
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        aria-label={`${t.accountMenu}: ${name}`}
        aria-expanded={isOpen}
        aria-controls={isOpen ? menuId : undefined}
        className={cn(
          `
            relative flex items-center gap-2 rounded-lg p-1 text-left focus-ring-inverse
            transition-colors
            before:absolute before:-inset-1
            hover:bg-sidebar-fg/10
            sm:pr-2
          `,
          isOpen && "bg-sidebar-fg/10",
        )}
      >
        <span aria-hidden className={cn(`
          grid size-8 shrink-0 place-items-center rounded-full bg-sidebar-active text-xs
          font-semibold text-sidebar
        `)}>
          {initials(name)}
        </span>
        <span className="hidden min-w-0 flex-col sm:flex">
          <span className="max-w-40 truncate text-sm/tight font-semibold">{name}</span>
          <span className="max-w-40 truncate text-xs opacity-70">{roleLabel}</span>
        </span>
        <ChevronDownIcon size={16} className={cn("hidden opacity-70 transition-transform sm:block", isOpen && `
          rotate-180
        `)} />
      </button>
      {isOpen ? (
        <div
          id={menuId}
          className={cn(`
            absolute top-full right-0 z-30 mt-2 w-56 origin-top-right animate-scale-in rounded-lg
            border bg-surface p-1 text-foreground shadow-card
          `)}
        >
          <div className="border-b px-3 py-2">
            <p className="truncate text-sm font-semibold">{name}</p>
            <p className="truncate text-xs text-muted">{roleLabel}</p>
          </div>
          {role === "admin" ? (
            <Link
              href="/admin/lich-su-thao-tac"
              onClick={() => setIsOpen(false)}
              className={cn(`
                mt-1 flex h-10 w-full items-center gap-2 rounded-md px-3 text-sm font-medium
                focus-ring
                hover:bg-primary-soft/60 hover:text-primary
              `)}
            >
              <HistoryIcon size={16} />
              {t.auditLog}
            </Link>
          ) : null}
          <LogoutButton
            area="admin"
            className={cn(`
              mt-1 flex h-10 w-full items-center gap-2 rounded-md px-3 text-sm font-medium
              text-danger focus-ring
              hover:bg-danger-soft
              disabled:opacity-50
            `)}
          >
            <LogOutIcon size={16} />
            {t.logout}
          </LogoutButton>
        </div>
      ) : null}
    </div>
  );
}
