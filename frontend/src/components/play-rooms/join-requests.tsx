"use client";

import { useState, useSyncExternalStore } from "react";
import { Avatar } from "@/components/member-area/avatar";
import { BottomSheet } from "@/components/ui/bottom-sheet";
import { Button } from "@/components/ui/button";
import { UserCheckIcon } from "@/components/ui/icons";
import type { PendingPerson } from "./types";

// "Chờ duyệt (k)" của Host (T-032 AC9): nút icon kèm số; desktop = popover dưới nút, dưới lg = bảng trượt từ đáy.
// Mỗi yêu cầu: avatar, tên, "Xin vào x phút trước", Từ chối / Duyệt.

const DESKTOP = "(min-width: 1024px)";
function useIsDesktop() {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia(DESKTOP);
      m.addEventListener("change", cb);
      return () => m.removeEventListener("change", cb);
    },
    () => window.matchMedia(DESKTOP).matches,
    () => false,
  );
}

const ago = (createdAt: string, nowMs: number) => {
  const min = Math.max(0, Math.floor((nowMs - Date.parse(createdAt)) / 60000));
  return min < 1 ? "vừa xong" : min < 60 ? `${min} phút trước` : `${Math.floor(min / 60)} giờ trước`;
};

type Props = {
  requests: PendingPerson[];
  /** Phòng đã đủ 8 người: khóa "Duyệt". */
  full: boolean;
  busy: boolean;
  nowMs: number;
  onDecide: (q: PendingPerson, approve: boolean) => void;
};

export function JoinRequests({ requests, full, busy, nowMs, onDecide }: Props) {
  const [open, setOpen] = useState(false);
  const desktop = useIsDesktop();
  const title = `Chờ duyệt vào phòng (${requests.length})`;

  const list = (
    <ul className="divide-y divide-border">
      {requests.map((q) => (
        <li key={q.id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 px-3 py-3">
          <span className="flex min-w-0 items-center gap-2.5">
            <Avatar url={q.avatar_url} name={q.display_name} size={36} />
            <span className="min-w-0">
              <span className="flex items-center gap-1.5">
                <span className="truncate text-sm font-semibold">{q.display_name}</span>
                <span className="shrink-0 rounded-full bg-primary-softer px-2 py-0.5 text-xs font-semibold text-primary ring-1 ring-primary/20">{q.tier ?? "Chưa xếp hạng"}</span>
              </span>
              <span className="block text-xs text-muted">Xin vào {ago(q.created_at, nowMs)}</span>
            </span>
          </span>
          <span className="flex gap-2">
            <Button variant="secondary" className="h-10 sm:h-10" onClick={() => onDecide(q, false)} disabled={busy}>
              Từ chối
            </Button>
            <Button
              className="h-10 sm:h-10"
              onClick={() => onDecide(q, true)}
              disabled={busy || full}
              title={full ? "Phòng đã đủ 8 người." : undefined}
            >
              Duyệt
            </Button>
          </span>
        </li>
      ))}
    </ul>
  );

  return (
    <div className="relative" onBlur={(e) => desktop && !e.currentTarget.contains(e.relatedTarget) && setOpen(false)}>
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={title}
        title={title}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        disabled={requests.length === 0}
        className="relative grid size-11 place-items-center rounded-lg border border-primary bg-surface text-primary hover:bg-primary-softer focus-ring disabled:cursor-not-allowed disabled:opacity-50 sm:size-10"
      >
        <UserCheckIcon size={20} />
        {requests.length > 0 ? (
          <span aria-hidden className="absolute -top-2 -right-2 grid min-w-5 place-items-center rounded-full bg-accent px-1.5 text-xs leading-5 font-bold text-cta-fg">
            {requests.length}
          </span>
        ) : null}
      </button>
      {open && desktop && requests.length > 0 ? (
        <div role="dialog" aria-label={title} onKeyDown={(e) => e.key === "Escape" && setOpen(false)} className="absolute right-0 z-30 mt-2 w-[22rem] rounded-card bg-surface shadow-card ring-1 ring-border">
          <h3 className="px-4 pt-3 pb-1 text-sm font-bold">{title}</h3>
          {list}
        </div>
      ) : null}
      {!desktop ? (
        <BottomSheet open={open && requests.length > 0} onClose={() => setOpen(false)} title={title}>
          {list}
        </BottomSheet>
      ) : null}
    </div>
  );
}
