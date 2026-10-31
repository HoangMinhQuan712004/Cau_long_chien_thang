"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { roomsApi } from "@/components/play-rooms/requests";
import type { NotificationItem } from "@/components/play-rooms/types";
import { usePolling } from "@/hooks/use-polling";
import { cn } from "@/lib/cn";
import { formatDate, formatTime } from "@/lib/format";
import { useMember } from "./member-shell";

/** Chuông thông báo trong web (T-017 AC22): chấm số chưa đọc, danh sách, "Đã đọc hết", bấm một dòng → tới phòng. */
export function NotificationBell() {
  const { leave } = useMember();
  const router = useRouter();
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);

  const apply = useCallback((res: Awaited<ReturnType<typeof roomsApi.listNotifications>>) => {
    if (!res.ok) return;
    setItems(res.data.items);
    setUnread(res.data.unread_count);
  }, []);
  const load = useCallback(async () => apply(await roomsApi.listNotifications()), [apply]);

  useEffect(() => {
    let cancelled = false;
    void roomsApi.listNotifications().then((res) => !cancelled && apply(res));
    return () => {
      cancelled = true;
    };
  }, [apply]);
  usePolling(() => void load(), 15000);

  async function readAll() {
    await roomsApi.readAll();
    await load();
  }

  async function openItem(n: NotificationItem) {
    setOpen(false);
    if (!n.read) await roomsApi.readOne(n.id);
    if (n.link) leave(() => router.push(n.link as string));
    void load();
  }

  return (
    <div className="relative" onBlur={(e) => !e.currentTarget.contains(e.relatedTarget) && setOpen(false)}>
      <button
        type="button"
        aria-label={unread > 0 ? `Thông báo, ${unread} chưa đọc` : "Thông báo"}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        className="relative grid size-10 place-items-center rounded-full hover:bg-primary-softer focus-ring"
      >
        <svg viewBox="0 0 20 20" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden>
          <path d="M5 8a5 5 0 0 1 10 0c0 4 1.5 5.5 1.5 5.5h-13S5 12 5 8ZM8.5 16.5a1.6 1.6 0 0 0 3 0" />
        </svg>
        {unread > 0 ? (
          <span className="absolute top-0.5 right-0.5 grid min-w-4.5 place-items-center rounded-full bg-danger px-1 text-[11px] leading-[18px] font-bold text-surface" aria-hidden>
            {unread > 9 ? "9+" : unread}
          </span>
        ) : null}
      </button>
      {open ? (
        <div role="dialog" aria-label="Thông báo" className="absolute right-0 z-40 mt-2 w-[min(22rem,calc(100vw-1.5rem))] rounded-card bg-surface shadow-card ring-1 ring-border">
          <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
            <h2 className="text-sm font-bold">Thông báo{unread > 0 ? ` · ${unread}` : ""}</h2>
            <button type="button" onClick={() => void readAll()} disabled={unread === 0} className="rounded-sm text-xs font-semibold text-primary hover:underline focus-ring disabled:text-subtle disabled:no-underline">
              Đã đọc hết
            </button>
          </div>
          <ul className="max-h-96 overflow-y-auto">
            {items.length === 0 ? (
              <li className="px-4 py-8 text-center text-sm text-muted">Chưa có thông báo nào.</li>
            ) : (
              items.map((n) => (
                <li key={n.id} className="border-b border-border last:border-0">
                  <button type="button" onClick={() => void openItem(n)} className={cn("flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-primary-softer focus-ring", !n.read && "bg-primary-softer")}>
                    <span aria-hidden className={cn("mt-1.5 size-2 shrink-0 rounded-full", n.read ? "bg-transparent" : "bg-primary")} />
                    <span className="min-w-0">
                      <span className={cn("block text-sm", !n.read && "font-semibold")}>{n.text}</span>
                      <span className="block text-xs text-subtle">
                        {formatDate(n.created_at)} · {formatTime(n.created_at)}
                      </span>
                    </span>
                  </button>
                </li>
              ))
            )}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
