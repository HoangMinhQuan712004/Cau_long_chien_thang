"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { ConfirmDialog } from "@/components/play-rooms/confirm-dialog";
import { AvatarImage } from "@/components/ui/avatar";
import { adminLogout } from "@/lib/api/auth";
import { can } from "./forbidden";
import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";
import { ChevronDownIcon, HistoryIcon, LogOutIcon, Svg, UserIcon } from "@/components/ui/icons";

type Props = {
  /** Mã quyền của phiên: "Lịch sử thao tác" chỉ hiện khi có audit_log.view. */
  perms: string[];
  name: string;
  /** Ảnh đại diện; null ⇒ chữ viết tắt. */
  avatarUrl: string | null;
  roleLabel: string;
  t: Dictionary["adminNav"];
};

/** Khiên (mục Phân quyền & menu); bộ icon chung chưa có. */
const ShieldIcon = () => (
  <Svg size={16}>
    <path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6z" />
    <path d="M9 12l2 2 4-4" />
  </Svg>
);

/** Mục link trong menu tài khoản (Phân quyền & menu). */
const MENU_ITEM = "mt-1 flex h-10 w-full items-center gap-2 rounded-md px-3 text-sm font-medium focus-ring hover:bg-primary-soft/60 hover:text-primary";

// "Nguyễn Văn An" ⇒ "VA"; "Admin" ⇒ "AD"
function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const letters = words.length > 1 ? words.slice(-2).map((w) => w[0]) : [...(words[0] ?? "?")].slice(0, 2);
  return letters.join("").toLocaleUpperCase("vi");
}

/** Tài khoản trên header: bấm mở menu nhỏ (tên, vai trò, Hồ sơ của tôi, Lịch sử thao tác – theo quyền audit_log.view, Phân quyền & menu – roles.manage, Đăng xuất có hỏi xác nhận); đóng bằng Esc hoặc bấm ra ngoài. */
export function AccountMenu({ perms, name, avatarUrl, roleLabel, t }: Props) {
  const [isOpen, setIsOpen] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
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
          grid size-8 shrink-0 place-items-center overflow-hidden rounded-full bg-sidebar-active
          text-xs font-semibold text-sidebar
        `)}>
          <AvatarImage url={avatarUrl} fallback={initials(name)} />
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
          <Link
            href="/admin/ho-so"
            onClick={() => setIsOpen(false)}
            className={cn(`
              mt-1 flex h-10 w-full items-center gap-2 rounded-md px-3 text-sm font-medium
              focus-ring
              hover:bg-primary-soft/60 hover:text-primary
            `)}
          >
            <UserIcon size={16} />
            {t.profile}
          </Link>
          {can(perms, "audit_log.view") ? (
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
          {can(perms, "roles.manage") ? (
            <Link href="/admin/cai-dat/phan-quyen" onClick={() => setIsOpen(false)} className={MENU_ITEM}>
              <ShieldIcon />
              {t.accessSettings}
            </Link>
          ) : null}
          {/* Đăng xuất: đóng menu, hỏi xác nhận trước (chỉ menu admin; LogoutButton dùng chung giữ nguyên) */}
          <button
            type="button"
            onClick={() => {
              setIsOpen(false);
              setIsConfirming(true);
            }}
            className={cn(`
              mt-1 flex h-10 w-full items-center gap-2 rounded-md px-3 text-sm font-medium
              text-danger focus-ring
              hover:bg-danger-soft
            `)}
          >
            <LogOutIcon size={16} />
            {t.logout}
          </button>
        </div>
      ) : null}
      {isConfirming ? (
        <ConfirmDialog
          danger
          title={t.logoutConfirmTitle}
          body={t.logoutConfirmBody}
          cancelLabel={t.cancel}
          confirmLabel={t.logout}
          onClose={() => {
            setIsConfirming(false);
            // Hộp bị gỡ khỏi DOM (không qua dialog.close) ⇒ tự trả focus về nút tài khoản
            requestAnimationFrame(() => buttonRef.current?.focus());
          }}
          onConfirm={async () => {
            // ConfirmDialog tự chặn bấm lặp + hiện trạng thái đang xử lý
            await adminLogout();
            window.location.replace("/dang-nhap");
            return null;
          }}
        />
      ) : null}
    </div>
  );
}
