"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { api } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { site } from "@/lib/site";
import { Avatar } from "./avatar";
import { NotificationBell } from "./notification-bell";
import { maskPhone, type MemberMe } from "./types";

// Khung khu hội viên (T-016 AC5, AC6, AC15): menu 6 mục, nút tài khoản, hộp "Bạn có thay đổi chưa lưu".

type Ctx = {
  me: MemberMe;
  setMe: (m: MemberMe | ((cur: MemberMe) => MemberMe)) => void;
  /** Màn đang sửa gọi khi có / hết thay đổi chưa lưu (ref: không gây render lại). */
  setDirty: (dirty: boolean) => void;
  /** Chạy `go` ngay; nếu đang có thay đổi chưa lưu thì hỏi E-007 trước. */
  leave: (go: () => void) => void;
};

const MemberCtx = createContext<Ctx | null>(null);

export function useMember(): Ctx {
  const c = useContext(MemberCtx);
  if (!c) throw new Error("useMember ngoài MemberShell");
  return c;
}

export const HOME_HREF = "/hoi-vien/ho-so";

const NAV = [
  { href: "/hoi-vien", label: "Tổng quan", exact: true },
  { href: "/hoi-vien/dat-san", label: "Đặt sân" },
  { href: "/hoi-vien/ho-so", label: "Hồ sơ của tôi" },
  { href: "/hoi-vien/video-ky-luc", label: "Video & kỷ lục" },
  { href: "/hoi-vien/danh-sach-san", label: "Danh sách sân", also: "/hoi-vien/phong" },
  { href: "/hoi-vien/lich-su-thanh-toan", label: "Lịch sử thanh toán" },
] as const;

export function MemberShell({ initial, children }: { initial: MemberMe; children: React.ReactNode }) {
  const [me, setMe] = useState(initial);
  const [asking, setAsking] = useState(false);
  const dirtyRef = useRef(false);
  const pendingRef = useRef<(() => void) | null>(null);

  const setDirty = useCallback((d: boolean) => {
    dirtyRef.current = d;
  }, []);
  const leave = useCallback((go: () => void) => {
    if (!dirtyRef.current) return go();
    pendingRef.current = go;
    setAsking(true);
  }, []);

  // Đóng / tải lại tab khi chưa lưu: hộp mặc định của trình duyệt
  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (!dirtyRef.current) return;
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, []);

  // Back lấy trang từ bfcache ⇒ tải lại để máy chủ kiểm phiên (như LogoutButton)
  useEffect(() => {
    const onPageShow = (e: PageTransitionEvent) => {
      if (e.persisted) window.location.reload();
    };
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, []);

  const value = useMemo<Ctx>(() => ({ me, setMe, setDirty, leave }), [me, setDirty, leave]);

  return (
    <MemberCtx.Provider value={value}>
      <MemberHeader />
      <main className="flex-1">{children}</main>
      <Modal
        open={asking}
        onClose={() => setAsking(false)}
        title="Bạn có thay đổi chưa lưu"
        footer={
          <>
            <Button variant="secondary" onClick={() => setAsking(false)}>
              Ở lại
            </Button>
            <Button
              onClick={() => {
                const go = pendingRef.current;
                pendingRef.current = null;
                dirtyRef.current = false;
                setAsking(false);
                go?.();
              }}
            >
              Bỏ thay đổi
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted">Rời trang sẽ bỏ các thay đổi này.</p>
      </Modal>
    </MemberCtx.Provider>
  );
}

function MemberHeader() {
  const { me, leave } = useMember();
  const pathname = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);

  // Điều hướng trong khu hội viên: có thay đổi chưa lưu thì hỏi trước (E-007)
  const go = (href: string) => (e: React.MouseEvent) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    setMenuOpen(false);
    leave(() => router.push(href));
  };

  async function logout() {
    await api.POST("/api/v1/auth/logout").catch(() => {});
    window.location.replace("/");
  }

  const isActive = (n: (typeof NAV)[number]) =>
    "exact" in n ? pathname === n.href : pathname.startsWith(n.href) || ("also" in n && pathname.startsWith(n.also));

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-surface">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-3 px-4 lg:gap-8">
        <button
          type="button"
          aria-label="Mở menu"
          aria-expanded={menuOpen}
          aria-controls="member-nav"
          onClick={() => setMenuOpen((o) => !o)}
          className="-ml-2 grid size-10 place-items-center rounded-lg text-foreground hover:bg-primary-softer focus-ring lg:hidden"
        >
          <svg viewBox="0 0 20 20" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
            <path d="M3 5.5h14M3 10h14M3 14.5h14" />
          </svg>
        </button>

        <Link href={HOME_HREF} onClick={go(HOME_HREF)} className="flex min-w-0 items-center gap-2 font-bold text-primary">
          <span aria-hidden className="grid size-8 shrink-0 place-items-center rounded-lg bg-primary text-xs text-surface">
            CL
          </span>
          <span className="truncate">{site.shortName}</span>
        </Link>

        <nav aria-label="Khu hội viên" id="member-nav" className="hidden h-full items-stretch gap-1 lg:flex">
          {NAV.map((n) => (
            <NavLink key={n.href} n={n} active={isActive(n)} onClick={go(n.href)} />
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2">
        <NotificationBell />
        <div className="relative" onBlur={(e) => !e.currentTarget.contains(e.relatedTarget) && setAccountOpen(false)}>
          <button
            type="button"
            aria-haspopup="menu"
            aria-expanded={accountOpen}
            onClick={() => setAccountOpen((o) => !o)}
            onKeyDown={(e) => e.key === "Escape" && setAccountOpen(false)}
            className="flex h-10 items-center gap-2 rounded-full border border-border py-1 pr-3 pl-1 hover:bg-primary-softer focus-ring"
          >
            <Avatar url={me.avatar_url} name={me.short_name} size={32} />
            <span className="max-w-24 truncate text-sm font-medium">{me.short_name}</span>
            <span aria-hidden className="text-xs text-muted">
              ▾
            </span>
          </button>
          {accountOpen ? (
            <div role="menu" className="absolute right-0 z-40 mt-2 w-64 rounded-card bg-surface p-2 shadow-card ring-1 ring-border">
              <div className="px-3 py-2">
                <p className="font-semibold break-words">{me.full_name}</p>
                <p className="text-sm text-muted">{maskPhone(me.phone)}</p>
              </div>
              <div className="my-1 border-t border-border" />
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setAccountOpen(false);
                  leave(() => void logout());
                }}
                className="w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-primary-softer hover:text-danger focus-ring"
              >
                Đăng xuất
              </button>
            </div>
          ) : null}
        </div>
        </div>
      </div>

      {menuOpen ? (
        <nav aria-label="Khu hội viên" className="border-t border-border bg-surface px-2 py-2 lg:hidden">
          <ul className="mx-auto flex max-w-6xl flex-col">
            {NAV.map((n) => (
              <li key={n.href}>
                <Link
                  href={n.href}
                  onClick={go(n.href)}
                  aria-current={isActive(n) ? "page" : undefined}
                  className={cn(
                    "block rounded-lg px-3 py-3 text-sm hover:bg-primary-softer",
                    isActive(n) ? "font-bold text-primary" : "font-medium",
                  )}
                >
                  {n.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      ) : null}
    </header>
  );
}

function NavLink({ n, active, onClick }: { n: (typeof NAV)[number]; active: boolean; onClick: (e: React.MouseEvent) => void }) {
  return (
    <Link
      href={n.href}
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={cn(
        "relative flex items-center px-2 text-sm whitespace-nowrap hover:text-primary focus-ring",
        active ? "font-bold text-primary" : "text-muted",
      )}
    >
      {n.label}
      {active ? <span aria-hidden className="absolute inset-x-1 bottom-0 h-0.5 rounded-full bg-primary" /> : null}
    </Link>
  );
}
