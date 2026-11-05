"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ConfirmDialog } from "@/components/play-rooms/confirm-dialog";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Svg } from "@/components/ui/icons";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";
import type { Dictionary } from "@/i18n/dictionaries";
import { api, errorMessage } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { toast } from "@/lib/feedback";
import { formatDayMonth, formatTime, vnDate } from "@/lib/format";

// Nội dung bảng "Nơi bạn đăng nhập" (kiểu Meta): thiết bị này + lần đăng nhập trên thiết bị khác
// (thiết bị, trình duyệt, giờ đăng nhập; không thành phố, không IP).

type AdminSession = components["schemas"]["MySessionOut"];
type T = Dictionary["adminProfile"];

const fill = (s: string, vars: Record<string, string | number>) => s.replace(/\{(\w+)\}/g, (m, k: string) => String(vars[k] ?? m));
/** "Chrome trên Linux"; thiếu trình duyệt ⇒ "Trình duyệt không xác định". */
const deviceName = (s: AdminSession, t: T) => (s.browser ? (s.os ? fill(t.deviceOn, { browser: s.browser, os: s.os }) : s.browser) : t.unknownBrowser);
const signedIn = (iso: string, t: T) => fill(t.signedInAt, { time: `${formatDayMonth(vnDate(iso))} ${formatTime(iso)}` });

/** Màn hình (máy tính) / điện thoại / máy tính bảng. */
function DeviceIcon({ type }: { type: AdminSession["device_type"] }) {
  if (type === "mobile") return <Svg size={20}><rect x="7" y="2.5" width="10" height="19" rx="2" /><path d="M11 18.5h2" /></Svg>;
  if (type === "tablet") return <Svg size={20}><rect x="4.5" y="2.5" width="15" height="19" rx="2" /><path d="M11 18.5h2" /></Svg>;
  return <Svg size={20}><rect x="2.5" y="4" width="19" height="12.5" rx="1.5" /><path d="M8 20.5h8M12 16.5v4" /></Svg>;
}

/** Một thiết bị: viền bo nhẹ như Meta (bảng con là lớp phủ, không có thẻ nào khác bên trong). */
function DeviceRow({ s, t, action }: { s: AdminSession; t: T; action?: React.ReactNode }) {
  return (
    <li className="flex items-center gap-3 rounded-xl border p-3">
      <span aria-hidden className="shrink-0 text-primary"><DeviceIcon type={s.device_type} /></span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="text-sm font-semibold wrap-anywhere">{deviceName(s, t)}</span>
        <span className="text-ui text-muted tabular-nums">{signedIn(s.created_at, t)}</span>
        {s.is_current ? <span className="text-ui font-semibold text-primary">{t.thisDevice}</span> : null}
      </span>
      {action}
    </li>
  );
}

export function SessionsPanel({ t }: { t: T }) {
  const router = useRouter();
  // undefined = đang tải, null = lỗi
  const [sessions, setSessions] = useState<AdminSession[] | null | undefined>(undefined);
  const [confirm, setConfirm] = useState<AdminSession | "all" | null>(null);
  // Nút vừa mở hộp xác nhận: hộp bị gỡ khỏi DOM (không qua dialog.close) nên tự trả focus về nút này
  const opener = useRef<HTMLElement | null>(null);
  function ask(target: AdminSession | "all") {
    opener.current = document.activeElement as HTMLElement | null;
    setConfirm(target);
  }
  function closeConfirm() {
    setConfirm(null);
    const el = opener.current;
    requestAnimationFrame(() => el?.isConnected && el.focus()); // thiết bị vừa đăng xuất ⇒ nút đã mất, bỏ qua
  }

  const load = useCallback(async () => {
    try {
      const { data } = await api.GET("/api/v1/admin/account/sessions");
      setSessions(data ?? null);
    } catch {
      setSessions(null);
    }
  }, []);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải khi mở bảng
    void load();
  }, [load]);

  // Đăng xuất 1 thiết bị / tất cả thiết bị khác; trả lỗi (chuỗi) để hiện trong hộp xác nhận
  async function revoke(target: AdminSession | "all"): Promise<string | null> {
    try {
      const res =
        target === "all"
          ? await api.POST("/api/v1/admin/account/sessions/revoke-others")
          : await api.DELETE("/api/v1/admin/account/sessions/{session_id}", { params: { path: { session_id: target.id } } });
      if (!res.response.ok) {
        // Thiết bị đã tự đăng xuất (404) ⇒ tải lại danh sách, báo nhẹ
        if (res.response.status !== 404) return errorMessage(res.error, t.unavailable);
        toast(errorMessage(res.error, t.sessionGone), undefined, "info");
        closeConfirm();
        await load();
        router.refresh();
        return null;
      }
      toast(target === "all" ? fill(t.signedOutAll, { n: (res.data as { revoked?: number } | undefined)?.revoked ?? 0 }) : t.signedOutOne);
      closeConfirm();
      await load();
      router.refresh(); // số thiết bị ở dòng "Nơi bạn đăng nhập"
      return null;
    } catch {
      return t.network;
    }
  }

  if (sessions === undefined) return <Skeleton className="h-40 w-full rounded-xl" />;
  if (sessions === null) return <Alert variant="error">{t.sessionsError}</Alert>;
  const current = sessions.find((s) => s.is_current);
  const others = sessions.filter((s) => !s.is_current);

  return (
    <div className="flex flex-col gap-6">
      {current ? <ul><DeviceRow s={current} t={t} /></ul> : null}
      <section aria-labelledby="other-devices" className="flex flex-col gap-3">
        <h3 id="other-devices" className="text-sm font-semibold">{t.otherDevices}</h3>
        {others.length ? (
          <ul className="flex flex-col gap-2">
            {others.map((s) => (
              <DeviceRow key={s.id} s={s} t={t} action={
                <Button variant="secondary" onClick={() => ask(s)} aria-label={`${t.signOut}: ${deviceName(s, t)}`}>{t.signOut}</Button>
              } />
            ))}
          </ul>
        ) : <p className="text-ui text-muted">{t.onlyThis}</p>}
        {others.length ? (
          <button type="button" onClick={() => ask("all")} className={cn(`
            -my-1 self-start rounded-sm py-2.5 text-ui font-semibold text-danger focus-ring
            hover:underline
          `)}>
            {t.signOutAll}
          </button>
        ) : null}
      </section>
      {confirm ? (
        <ConfirmDialog
          danger
          title={confirm === "all" ? t.confirmAllTitle : fill(t.confirmOneTitle, { device: deviceName(confirm, t) })}
          body={<p className="text-ui text-muted">{confirm === "all" ? t.confirmAllBody : t.confirmOneBody}</p>}
          cancelLabel={t.cancel}
          confirmLabel={t.signOut}
          onClose={closeConfirm}
          onConfirm={() => revoke(confirm)}
        />
      ) : null}
    </div>
  );
}
