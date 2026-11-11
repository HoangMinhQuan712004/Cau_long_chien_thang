"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DatePicker } from "@/components/ui/date-picker";
import { IconButton } from "@/components/ui/icon-button";
import { ChevronLeftIcon, ChevronRightIcon } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { usePolling } from "@/hooks/use-polling";
import { errorText } from "@/lib/api/write";
import { addDaysIso, formatLongDate, formatTime, todayVn } from "@/lib/format";
import { MonitorRoomCard } from "./room-card";
import { type MonitorTarget, RoomDetailDialog } from "./room-detail-dialog";
import { getMonitorDay } from "./requests";
import type { MonitorCourt, MonitorDay } from "./types";

// /admin/theo-doi-san (T-069): mỗi sân một hàng, các phòng trong ngày cuộn ngang (như Danh sách sân, T-054).
// Chỉ đọc. Hôm nay tự tải lại mỗi 10 giây; ngày khác không tự tải lại.

const REFRESH_MS = 10_000;
const LIMIT_DAYS = 365; // API chỉ nhận ±1 năm quanh hôm nay

export function MonitorScreen() {
  const [today] = useState(() => todayVn());
  const [date, setDate] = useState(today);
  const [data, setData] = useState<MonitorDay | null>(null);
  const [error, setError] = useState("");
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [target, setTarget] = useState<MonitorTarget | null>(null);
  const seq = useRef(0);
  const isToday = date === today;

  const load = useCallback(async (day: string) => {
    const mine = ++seq.current;
    const res = await getMonitorDay(day);
    if (mine !== seq.current) return; // chỉ nhận kết quả của ngày đang xem
    if (res.ok) {
      setData(res.data);
      setError("");
      setUpdatedAt(new Date().toISOString());
    } else if (res.error.status === 403) setError("Bạn không có quyền xem Theo dõi sân.");
    else if (res.error.status !== 401) setError(errorText(res.error));
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải khi đổi ngày
    void load(date);
  }, [load, date]);
  usePolling(() => {
    if (isToday) void load(date);
  }, REFRESH_MS);

  const shown = data && data.date === date ? data : null;
  const courts = useMemo(() => shown?.courts ?? [], [shown]);
  const totals = useMemo(() => {
    const all = courts.flatMap((c) => c.rooms);
    return { playing: all.filter((r) => r.status === "playing").length, upcoming: all.filter((r) => r.status === "upcoming").length, ended: all.filter((r) => r.status === "ended").length, total: all.length };
  }, [courts]);

  const go = (d: string) => {
    if (d >= addDaysIso(today, -LIMIT_DAYS) && d <= addDaysIso(today, LIMIT_DAYS)) setDate(d);
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Theo dõi sân"
        description="Các phòng chơi theo từng sân, chỉ xem."
        aside={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <IconButton icon={<ChevronLeftIcon />} label="Ngày trước" onClick={() => go(addDaysIso(date, -1))} disabled={date <= addDaysIso(today, -LIMIT_DAYS)} />
            <DatePicker value={date} today={today} onChange={go} className="w-44" />
            <IconButton icon={<ChevronRightIcon />} label="Ngày sau" onClick={() => go(addDaysIso(date, 1))} disabled={date >= addDaysIso(today, LIMIT_DAYS)} />
            {isToday ? null : (
              <Button variant="secondary" onClick={() => go(today)}>
                Hôm nay
              </Button>
            )}
          </div>
        }
      />

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
        <span className="font-semibold text-foreground">{formatLongDate(date)}</span>
        {shown ? (
          <>
            <span>
              <b className="text-foreground tabular-nums">{totals.playing}</b> đang chơi · <b className="text-foreground tabular-nums">{totals.upcoming}</b> sắp tới ·{" "}
              <b className="text-foreground tabular-nums">{totals.ended}</b> đã kết thúc
            </span>
            <span role="status" className="text-xs">
              {isToday && updatedAt ? `Tự cập nhật mỗi 10 giây · lúc ${formatTime(updatedAt)}` : "Ngày đã chọn không tự cập nhật"}
            </span>
          </>
        ) : null}
      </div>

      {error ? (
        <div role="alert" className="rounded-card bg-surface p-8 text-center shadow-card">
          <p className="font-semibold">{error}</p>
          <Button className="mt-4" onClick={() => void load(date)}>
            Thử lại
          </Button>
        </div>
      ) : !shown ? (
        <MonitorSkeleton />
      ) : courts.length === 0 ? (
        <p className="rounded-card bg-surface p-8 text-center text-muted shadow-card">Chưa có sân nào.</p>
      ) : (
        <div className="space-y-4">
          {courts.map((c) => (
            <CourtRow key={c.resource_code} court={c} onOpen={(id) => setTarget({ id, courtName: c.resource_name })} />
          ))}
        </div>
      )}

      <RoomDetailDialog target={target} live={isToday} onClose={() => setTarget(null)} />
    </div>
  );
}

/** Một sân: tiêu đề + hàng phòng cuộn ngang (điện thoại tràn sát mép, có snap; vùng cuộn focus được nên dùng được phím mũi tên). */
function CourtRow({ court: c, onOpen }: { court: MonitorCourt; onOpen: (roomId: number) => void }) {
  return (
    <section aria-label={c.resource_name} className="rounded-card bg-surface p-4 shadow-card">
      <h2 className="flex flex-wrap items-center gap-2 font-bold">
        {c.resource_name}
        <span className="text-xs font-normal text-muted tabular-nums">{c.rooms.length ? `${c.rooms.length} phòng` : ""}</span>
        {c.is_active ? null : <Badge variant="neutral">Ngừng hoạt động</Badge>}
      </h2>
      {c.rooms.length === 0 ? (
        <p className="mt-3 rounded-lg bg-background px-3 py-4 text-center text-sm text-muted">Không có phòng</p>
      ) : (
        <div
          role="group"
          tabIndex={0}
          aria-label={`Các phòng của ${c.resource_name}`}
          className="-mx-4 mt-3 flex snap-x snap-mandatory scroll-px-4 gap-3 overflow-x-auto px-4 pb-2 focus-ring sm:mx-0 sm:snap-none sm:px-0"
        >
          {c.rooms.map((r) => (
            <div key={r.room_id} className="flex w-[80%] max-w-72 shrink-0 snap-start sm:w-72">
              <MonitorRoomCard room={r} onOpen={() => onOpen(r.room_id)} />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function MonitorSkeleton() {
  return (
    <div className="space-y-4" aria-busy>
      <p role="status" className="sr-only">
        Đang tải…
      </p>
      {[0, 1, 2].map((i) => (
        <div key={i} className="rounded-card bg-surface p-4 shadow-card">
          <Skeleton className="h-5 w-24" />
          <div className="mt-3 flex gap-3 overflow-hidden">
            {[0, 1, 2].map((j) => (
              <Skeleton key={j} className="h-36 w-72 shrink-0 rounded-xl" />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
