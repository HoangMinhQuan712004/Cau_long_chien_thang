"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { BottomSheet } from "@/components/ui/bottom-sheet";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { api } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { formatLongDate, vnDate, vnMinutes } from "@/lib/format";
import { site } from "@/lib/site";
import { Avatar } from "./avatar";
import { NotificationBell } from "./notification-bell";
import { maskPhone, type MemberMe } from "./types";

// Khung khu hội viên (T-016 AC5, AC6, AC15; T-028 AC1–AC3):
// · từ lg: header ngang (8 mục, hết chỗ thì gom vào "…");
// · dưới lg: app bar xanh trên (quay lại + tiêu đề) + thanh điều hướng dưới 5 mục, nút "Đặt sân" tròn nổi giữa.
// Hộp "Bạn có thay đổi chưa lưu" dùng chung.

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

export const HOME_HREF = "/hoi-vien";

const NAV = [
  { href: "/hoi-vien", label: "Tổng quan", exact: true },
  { href: "/hoi-vien/dat-san", label: "Đặt sân" },
  { href: "/hoi-vien/ho-so", label: "Hồ sơ của tôi" },
  { href: "/hoi-vien/lich-su-choi", label: "Lịch sử chơi" },
  { href: "/hoi-vien/video-ky-luc", label: "Video & kỷ lục" },
  { href: "/hoi-vien/bang-xep-hang", label: "Bảng xếp hạng" },
  { href: "/hoi-vien/danh-sach-san", label: "Danh sách sân", also: "/hoi-vien/phong" },
  { href: "/hoi-vien/lich-su-thanh-toan", label: "Lịch sử thanh toán" },
] as const;

type NavItem = (typeof NAV)[number];

/** Màn lg chỉ đủ chỗ cho 5 mục đầu; các mục còn lại gom vào "…" (xl trở lên hiện đủ). */
const PRIMARY_COUNT = 5;

/** Các mục nằm trong sheet "Tài khoản" của điện thoại (không có chỗ trên thanh dưới 5 mục). */
const ACCOUNT_LINKS = [
  { href: "/hoi-vien/ho-so", label: "Hồ sơ của tôi" },
  { href: "/hoi-vien/video-ky-luc", label: "Video & kỷ lục" },
  { href: "/hoi-vien/lich-su-choi", label: "Lịch sử chơi" },
  { href: "/hoi-vien/bang-xep-hang", label: "Bảng xếp hạng" },
] as const;

/** Tiêu đề app bar (in hoa) và màn cha để nút quay lại về đúng chỗ. */
const SCREENS: { prefix: string; title: string; back: string }[] = [
  { prefix: "/hoi-vien/dat-san", title: "Đặt sân", back: HOME_HREF },
  { prefix: "/hoi-vien/thanh-toan", title: "Thanh toán", back: "/hoi-vien/dat-san" },
  { prefix: "/hoi-vien/ho-so", title: "Hồ sơ của tôi", back: HOME_HREF },
  { prefix: "/hoi-vien/lich-su-choi", title: "Lịch sử chơi", back: HOME_HREF },
  { prefix: "/hoi-vien/video-ky-luc", title: "Video & kỷ lục", back: HOME_HREF },
  { prefix: "/hoi-vien/bang-xep-hang", title: "Bảng xếp hạng", back: HOME_HREF },
  { prefix: "/hoi-vien/danh-sach-san", title: "Danh sách sân", back: HOME_HREF },
  { prefix: "/hoi-vien/phong", title: "Phòng chơi", back: "/hoi-vien/danh-sach-san" },
  { prefix: "/hoi-vien/lich-su-thanh-toan", title: "Lịch sử thanh toán", back: HOME_HREF },
];

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
      {/* Chừa chỗ cho thanh điều hướng dưới (điện thoại); thanh tự ẩn khi màn có thanh hành động riêng */}
      <main className="flex-1 pb-24 lg:pb-0 [body:has([data-bottom-bar])_&]:pb-32 lg:[body:has([data-bottom-bar])_&]:pb-0">{children}</main>
      <BottomNav />
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

const isActive = (pathname: string, n: NavItem) =>
  "exact" in n ? pathname === n.href : pathname.startsWith(n.href) || ("also" in n && pathname.startsWith(n.also));

/** Điều hướng trong khu hội viên: có thay đổi chưa lưu thì hỏi trước (E-007). */
function useGo() {
  const { leave } = useMember();
  const router = useRouter();
  return (href: string, after?: () => void) => (e: React.MouseEvent) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    after?.();
    leave(() => router.push(href));
  };
}

async function logout() {
  await api.POST("/api/v1/auth/logout").catch(() => {});
  window.location.replace("/");
}

/** Giờ hiện tại (ms) sau khi trang đã dựng – tránh đọc đồng hồ lúc render. */
function useNowMs() {
  const [now, setNow] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => setNow(Date.now()), 0);
    return () => clearTimeout(t);
  }, []);
  return now;
}

const greetingOf = (nowMs: number) => {
  const hour = vnMinutes(new Date(nowMs).toISOString()) / 60;
  return hour >= 5 && hour < 11 ? "sáng" : hour >= 11 && hour < 18 ? "chiều" : "tối";
};

function MemberHeader() {
  const { me, leave } = useMember();
  const pathname = usePathname();
  const go = useGo();
  const [accountOpen, setAccountOpen] = useState(false);

  return (
    <>
      {/* ===== Điện thoại / tablet: app bar xanh ===== */}
      <MobileBar />

      {/* ===== Desktop: header ngang ===== */}
      <header className="sticky top-0 z-30 hidden border-b border-border bg-surface lg:block">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-8 px-4">
          <Link href={HOME_HREF} onClick={go(HOME_HREF)} className="flex min-w-0 items-center gap-2 font-bold text-primary">
            <span aria-hidden className="grid size-8 shrink-0 place-items-center rounded-lg bg-primary text-xs text-surface">
              CL
            </span>
            <span className="truncate">{site.shortName}</span>
          </Link>

          <nav aria-label="Khu hội viên" className="flex h-full items-stretch gap-1">
            {NAV.map((n, i) => (
              <NavLink key={n.href} n={n} active={isActive(pathname, n)} onClick={go(n.href)} className={i >= PRIMARY_COUNT ? "hidden xl:flex" : undefined} />
            ))}
            <MoreMenu items={NAV.slice(PRIMARY_COUNT)} pathname={pathname} />
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
      </header>
    </>
  );
}

/** App bar điện thoại: Tổng quan = đầu trang chào (AC2); các màn khác = quay lại + tiêu đề in hoa giữa + chuông (AC3). */
function MobileBar() {
  const { me } = useMember();
  const pathname = usePathname();
  const go = useGo();
  const now = useNowMs();
  const home = pathname === HOME_HREF;
  const screen = SCREENS.find((s) => pathname.startsWith(s.prefix));

  if (home) {
    return (
      <header className="relative overflow-hidden bg-appbar text-surface lg:hidden">
        <CourtPattern />
        <div className="relative flex items-center gap-3 px-4 pt-4 pb-5">
          <div className="min-w-0 flex-1">
            <p className="text-xs text-surface/80">{now ? formatLongDate(vnDate(new Date(now).toISOString())) : " "}</p>
            <p className="truncate text-lg leading-snug font-bold">
              Chào buổi {now ? greetingOf(now) : "…"}, <span className="text-accent-soft">{me.short_name}</span>
            </p>
          </div>
          <NotificationBell onDark />
          <Avatar url={me.avatar_url} name={me.short_name} size={40} className="ring-2 ring-surface/40" />
        </div>
      </header>
    );
  }

  return (
    <header className="sticky top-0 z-30 bg-appbar text-surface shadow-sm lg:hidden">
      <div className="grid h-14 grid-cols-[3rem_1fr_3rem] items-center px-1">
        <Link
          href={screen?.back ?? HOME_HREF}
          onClick={go(screen?.back ?? HOME_HREF)}
          aria-label="Quay lại"
          className="grid size-11 place-items-center rounded-full hover:bg-surface/15 focus-ring"
        >
          <svg viewBox="0 0 20 20" className="size-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M12.5 4 6.5 10l6 6" />
          </svg>
        </Link>
        <p className="truncate text-center text-[15px] font-bold tracking-wide uppercase">{screen?.title ?? "Khu hội viên"}</p>
        <NotificationBell onDark />
      </div>
    </header>
  );
}

/** Hoa văn sân cầu lông mờ nền đầu trang (AC2). */
function CourtPattern() {
  return (
    <svg aria-hidden viewBox="0 0 360 120" preserveAspectRatio="xMidYMid slice" className="pointer-events-none absolute inset-0 size-full text-surface opacity-[0.09]" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="20" y="10" width="320" height="100" />
      <path d="M180 10v100M20 60h320M20 28h320M20 92h320M70 10v100M290 10v100" />
      <circle cx="180" cy="60" r="18" />
    </svg>
  );
}

function NavLink({ n, active, onClick, className }: { n: NavItem; active: boolean; onClick: (e: React.MouseEvent) => void; className?: string }) {
  return (
    <Link
      href={n.href}
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={cn("relative flex items-center px-2 text-sm whitespace-nowrap hover:text-primary focus-ring", active ? "font-bold text-primary" : "text-muted", className)}
    >
      {n.label}
      {active ? <span aria-hidden className="absolute inset-x-1 bottom-0 h-0.5 rounded-full bg-primary" /> : null}
    </Link>
  );
}

/** Nút "…" (chỉ màn lg, dưới xl): mở danh sách các mục không đủ chỗ trên thanh menu. */
function MoreMenu({ items, pathname }: { items: readonly NavItem[]; pathname: string }) {
  const go = useGo();
  const [open, setOpen] = useState(false);
  const active = items.some((n) => isActive(pathname, n));
  return (
    <div className="relative flex items-stretch xl:hidden" onBlur={(e) => !e.currentTarget.contains(e.relatedTarget) && setOpen(false)}>
      <button
        type="button"
        aria-label="Thêm mục menu"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        className={cn("relative flex items-center px-2 text-sm hover:text-primary focus-ring", active ? "font-bold text-primary" : "text-muted")}
      >
        <span aria-hidden>···</span>
        {active ? <span aria-hidden className="absolute inset-x-1 bottom-0 h-0.5 rounded-full bg-primary" /> : null}
      </button>
      {open ? (
        <div role="menu" className="absolute top-full right-0 z-40 mt-1 w-56 rounded-card bg-surface p-1.5 shadow-card ring-1 ring-border">
          {items.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              role="menuitem"
              onClick={go(n.href, () => setOpen(false))}
              aria-current={isActive(pathname, n) ? "page" : undefined}
              className={cn("block rounded-lg px-3 py-2.5 text-sm hover:bg-primary-softer focus-ring", isActive(pathname, n) ? "font-bold text-primary" : "font-medium")}
            >
              {n.label}
            </Link>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Thanh điều hướng dưới (điện thoại / tablet): Tổng quan · Danh sách sân · [Đặt sân] · Lịch sử thanh toán · Tài khoản
// ---------------------------------------------------------------------------------------------

const ico = "size-6";
const stroke = { fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round", strokeLinejoin: "round" } as const;
const IconHome = () => (
  <svg viewBox="0 0 24 24" className={ico} {...stroke} aria-hidden>
    <path d="M4 11 12 4l8 7M6 9.5V20h12V9.5M10 20v-5h4v5" />
  </svg>
);
const IconCourts = () => (
  <svg viewBox="0 0 24 24" className={ico} {...stroke} aria-hidden>
    <rect x="3.5" y="5" width="17" height="14" rx="1.5" />
    <path d="M12 5v14M3.5 12h17M7.5 8v8M16.5 8v8" />
  </svg>
);
const IconReceipt = () => (
  <svg viewBox="0 0 24 24" className={ico} {...stroke} aria-hidden>
    <path d="M6 3.5h12V21l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6" />
  </svg>
);
const IconUser = () => (
  <svg viewBox="0 0 24 24" className={ico} {...stroke} aria-hidden>
    <circle cx="12" cy="8.5" r="3.5" />
    <path d="M5 20a7 7 0 0 1 14 0" />
  </svg>
);
const IconShuttle = () => (
  <svg viewBox="0 0 24 24" className="size-7" {...stroke} strokeWidth={1.9} aria-hidden>
    <path d="M9.6 15.6 6.2 5.2M12 15V4M14.4 15.6l3.4-10.4M6.2 5.2c3.6-1.7 7.9-1.7 11.6 0" />
    <circle cx="12" cy="18.6" r="2.5" />
  </svg>
);

function BottomNav() {
  const pathname = usePathname();
  const go = useGo();
  const { me, leave } = useMember();
  const [sheet, setSheet] = useState(false);
  // Trang thanh toán có thanh trên riêng và không cần thoát nửa chừng
  if (pathname.startsWith("/hoi-vien/thanh-toan")) return null;

  const accountActive = ACCOUNT_LINKS.some((l) => pathname.startsWith(l.href));
  const item = (href: string, label: string, icon: React.ReactNode, active: boolean) => (
    <Link
      key={href}
      href={href}
      onClick={go(href)}
      aria-current={active ? "page" : undefined}
      className={cn("flex min-h-14 flex-col items-center justify-center gap-0.5 px-1 text-[11px] leading-tight font-medium focus-ring", active ? "text-primary" : "text-muted")}
    >
      {icon}
      <span className="text-center">{label}</span>
    </Link>
  );
  const bookActive = pathname.startsWith("/hoi-vien/dat-san");

  return (
    <>
      {/* Ẩn khi màn có thanh hành động riêng (`data-bottom-bar`): xem globals.css */}
      <nav
        aria-label="Điều hướng chính"
        data-member-nav
        className="fixed inset-x-0 bottom-0 z-40 rounded-t-[20px] border-t border-border bg-surface pb-[env(safe-area-inset-bottom)] shadow-[0_-4px_18px_rgb(20_40_30/0.10)] lg:hidden"
      >
        <div className="mx-auto grid max-w-xl grid-cols-5 items-end">
          {item(HOME_HREF, "Tổng quan", <IconHome />, pathname === HOME_HREF)}
          {item("/hoi-vien/danh-sach-san", "Danh sách sân", <IconCourts />, pathname.startsWith("/hoi-vien/danh-sach-san") || pathname.startsWith("/hoi-vien/phong"))}
          <Link
            href="/hoi-vien/dat-san"
            onClick={go("/hoi-vien/dat-san")}
            aria-current={bookActive ? "page" : undefined}
            className="flex flex-col items-center justify-end gap-1 pb-1.5 text-[11px] leading-tight font-bold text-primary focus-ring"
          >
            <span
              className={cn(
                "-mt-7 grid size-14 place-items-center rounded-full bg-cta text-cta-fg shadow-[0_6px_16px_rgb(0_0_0/0.22)] ring-4 ring-surface",
                "transition-transform active:scale-95 motion-reduce:transition-none",
              )}
            >
              <IconShuttle />
            </span>
            Đặt sân
          </Link>
          {item("/hoi-vien/lich-su-thanh-toan", "Lịch sử thanh toán", <IconReceipt />, pathname.startsWith("/hoi-vien/lich-su-thanh-toan"))}
          <button
            type="button"
            aria-haspopup="dialog"
            aria-expanded={sheet}
            onClick={() => setSheet(true)}
            className={cn("flex min-h-14 flex-col items-center justify-center gap-0.5 px-1 text-[11px] leading-tight font-medium focus-ring", accountActive ? "text-primary" : "text-muted")}
          >
            <IconUser />
            Tài khoản
          </button>
        </div>
      </nav>

      <BottomSheet open={sheet} onClose={() => setSheet(false)} title="Tài khoản">
        <div className="flex items-center gap-3 px-3 py-2">
          <Avatar url={me.avatar_url} name={me.short_name} size={44} />
          <div className="min-w-0">
            <p className="truncate font-semibold">{me.full_name}</p>
            <p className="text-sm text-muted">{maskPhone(me.phone)}</p>
          </div>
        </div>
        <ul className="mt-1">
          {ACCOUNT_LINKS.map((l) => (
            <li key={l.href}>
              <Link
                href={l.href}
                onClick={go(l.href, () => setSheet(false))}
                aria-current={pathname.startsWith(l.href) ? "page" : undefined}
                className={cn("flex min-h-12 items-center justify-between rounded-xl px-3 text-sm hover:bg-primary-softer focus-ring", pathname.startsWith(l.href) ? "font-bold text-primary" : "font-medium")}
              >
                {l.label}
                <span aria-hidden className="text-muted">
                  ›
                </span>
              </Link>
            </li>
          ))}
          <li>
            <button
              type="button"
              onClick={() => {
                setSheet(false);
                // Mở danh sách thông báo ở chuông trên app bar
                window.dispatchEvent(new Event("member:open-notifications"));
              }}
              className="flex min-h-12 w-full items-center justify-between rounded-xl px-3 text-left text-sm font-medium hover:bg-primary-softer focus-ring"
            >
              Thông báo
              <span aria-hidden className="text-muted">
                ›
              </span>
            </button>
          </li>
        </ul>
        <div className="mx-3 my-2 border-t border-border" />
        <button
          type="button"
          onClick={() => {
            setSheet(false);
            leave(() => void logout());
          }}
          className="flex min-h-12 w-full items-center rounded-xl px-3 text-left text-sm font-semibold text-danger hover:bg-danger-soft focus-ring"
        >
          Đăng xuất
        </button>
      </BottomSheet>
    </>
  );
}
