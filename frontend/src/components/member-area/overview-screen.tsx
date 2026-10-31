"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Avatar } from "@/components/member-area/avatar";
import { PageBanner } from "@/components/member-area/page-banner";
import { roomsApi } from "@/components/play-rooms/requests";
import type { NotificationItem } from "@/components/play-rooms/types";
import { hourRange } from "@/components/play-rooms/utils";
import { Button } from "@/components/ui/button";
import { usePolling } from "@/hooks/use-polling";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/cn";
import { formatDate, formatDayMonth, formatLongDate, formatTime, vnMinutes } from "@/lib/format";
import { useMember } from "./member-shell";

// /hoi-vien (T-018 AC1–AC3): lời chào + số lịch hôm nay, "Lịch đặt sắp tới" (thẻ TIẾP THEO + tối đa 3 dòng), "Thông báo mới".

type Overview = components["schemas"]["Overview"];
type Upcoming = components["schemas"]["UpcomingItem"];

const btnLink =
  "inline-flex h-11 items-center justify-center rounded-lg px-4 text-sm font-semibold focus-ring sm:h-10";

/** 05–11 sáng, 11–18 chiều, còn lại tối (giờ Việt Nam). */
function greetingOf(nowMs: number): string {
  const hour = vnMinutes(new Date(nowMs).toISOString()) / 60;
  return hour >= 5 && hour < 11 ? "sáng" : hour >= 11 && hour < 18 ? "chiều" : "tối";
}

export function OverviewScreen() {
  const router = useRouter();
  const { leave } = useMember();
  const [data, setData] = useState<Overview | null>(null);
  const [failed, setFailed] = useState(false);
  // Mốc lúc tải gần nhất: dùng cho lời chào và "Còn n phút" (không đọc đồng hồ khi render)
  const [nowMs, setNowMs] = useState(0);
  const [notes, setNotes] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);

  const load = useCallback(async () => {
    try {
      const [ov, nt] = await Promise.all([api.GET("/api/v1/member-area/overview"), roomsApi.listNotifications()]);
      if (ov.response.status === 401) {
        window.location.replace(`/dang-nhap?next=${encodeURIComponent("/hoi-vien")}&ly-do=het-han`);
        return;
      }
      if (ov.data) {
        setData(ov.data);
        setNowMs(Date.now());
        setFailed(false);
      } else setFailed(true);
      if (nt.ok) {
        setNotes(nt.data.items.slice(0, 5));
        setUnread(nt.data.unread_count);
      }
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải lần đầu khi vào trang
    void load();
  }, [load]);
  usePolling(() => void load(), 15000);

  async function readAll() {
    await roomsApi.readAll();
    await load();
  }
  async function openNote(n: NotificationItem) {
    if (!n.read) await roomsApi.readOne(n.id);
    if (n.link) leave(() => router.push(n.link as string));
    else void load();
  }

  const [next, ...rest] = data?.upcoming ?? [];
  const more = rest.slice(0, 3);

  return (
    <>
      <PageBanner
        title={data ? `Chào buổi ${greetingOf(nowMs)}, ${data.greeting_name}` : "Tổng quan"}
        subtitle={data ? `${formatLongDate(data.today)} · Bạn có ${data.today_count} lịch chơi hôm nay` : "Đang tải…"}
        aside={
          <Link href="/hoi-vien/dat-san" className={cn(btnLink, "bg-surface text-primary-hover hover:bg-primary-softer")}>
            Đặt sân
          </Link>
        }
      />
      <div className="mx-auto grid max-w-6xl gap-4 px-4 py-6 sm:py-8 lg:grid-cols-[1.4fr_1fr]">
        {failed && !data ? (
          <div role="alert" className="rounded-card bg-surface p-8 text-center shadow-card lg:col-span-2">
            <p className="font-semibold">Không tải được tổng quan. Vui lòng thử lại.</p>
            <Button className="mt-4" onClick={() => void load()}>
              Thử lại
            </Button>
          </div>
        ) : !data ? (
          <p className="py-10 text-center text-muted lg:col-span-2" aria-busy>
            Đang tải…
          </p>
        ) : (
          <>
            <section className="rounded-card bg-surface p-4 shadow-card sm:p-5" aria-labelledby="up-title">
              <div className="flex items-center justify-between gap-3">
                <h2 id="up-title" className="text-base font-bold">
                  Lịch đặt sắp tới
                </h2>
                {next ? (
                  <Link href="/hoi-vien/danh-sach-san?loc=cua-toi" className="rounded-sm text-sm font-semibold text-primary hover:underline focus-ring">
                    Xem tất cả ›
                  </Link>
                ) : null}
              </div>
              {!next ? (
                <div className="py-8 text-center">
                  <p className="text-muted">Bạn chưa có lịch chơi sắp tới</p>
                  <Link href="/hoi-vien/dat-san" className={cn(btnLink, "mt-4 bg-primary text-surface hover:bg-primary-hover")}>
                    Đặt sân
                  </Link>
                </div>
              ) : (
                <>
                  <NextCard item={next} today={data.today} nowMs={nowMs} />
                  {more.length > 0 ? (
                    <ul className="mt-3 divide-y divide-border">
                      {more.map((it) => (
                        <li key={it.booking_code}>
                          <Row item={it} today={data.today} />
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </>
              )}
            </section>

            <section className="rounded-card bg-surface p-4 shadow-card sm:p-5" aria-labelledby="note-title">
              <div className="flex items-center justify-between gap-3">
                <h2 id="note-title" className="flex items-center gap-2 text-base font-bold">
                  Thông báo mới
                  {unread > 0 ? (
                    <span className="grid min-w-5 place-items-center rounded-full bg-danger px-1.5 text-xs leading-5 font-bold text-surface" aria-label={`${unread} chưa đọc`}>
                      {unread}
                    </span>
                  ) : null}
                </h2>
                <button type="button" onClick={() => void readAll()} disabled={unread === 0} className="rounded-sm text-sm font-semibold text-primary hover:underline focus-ring disabled:text-subtle disabled:no-underline">
                  Đã đọc hết
                </button>
              </div>
              {notes.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted">Chưa có thông báo nào.</p>
              ) : (
                <ul className="mt-3 divide-y divide-border">
                  {notes.map((n) => (
                    <li key={n.id}>
                      <button type="button" onClick={() => void openNote(n)} className="flex w-full items-start gap-3 rounded-lg py-3 text-left hover:bg-primary-softer focus-ring">
                        <span aria-hidden className={cn("mt-1.5 size-2 shrink-0 rounded-full", n.read ? "bg-transparent" : "bg-primary")} />
                        <span className="min-w-0">
                          <span className={cn("block text-sm", !n.read && "font-semibold")}>{n.text}</span>
                          <span className="block text-xs text-subtle">
                            {formatDate(n.created_at)} · {formatTime(n.created_at)}
                          </span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
      </div>
    </>
  );
}

const dayLabel = (playDate: string, today: string) => (playDate === today ? "Hôm nay" : formatDayMonth(playDate));

function HostTag({ role }: { role: Upcoming["role"] }) {
  return <span className="rounded-full bg-primary-softer px-2 py-0.5 text-xs font-semibold ring-1 ring-border">{role === "host" ? "Host" : "Thành viên"}</span>;
}

function NextCard({ item, today, nowMs }: { item: Upcoming; today: string; nowMs: number }) {
  const minutes = Math.ceil((Date.parse(item.start_at) - nowMs) / 60000);
  const badge = item.phase === "ongoing" ? "Đang diễn ra" : nowMs > 0 && minutes > 0 && minutes <= 60 ? `Còn ${minutes} phút` : null;
  return (
    <article className="mt-3 rounded-card border border-primary/25 bg-primary-softer p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold tracking-wide text-muted uppercase">Tiếp theo</p>
        {badge ? <span className="rounded-full bg-primary px-2.5 py-0.5 text-xs font-semibold text-surface">{badge}</span> : null}
      </div>
      <p className="mt-1 text-lg font-bold">
        {dayLabel(item.play_date, today)} · {hourRange(item.start_at, item.end_at)}
      </p>
      <p className="mt-1 text-sm">
        {item.resource_name} · {item.resource_type_name} · Host: <b className="font-semibold">{item.role === "host" ? "bạn" : item.host_name}</b>
      </p>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        {item.capacity !== null ? (
          <div className="flex items-center gap-2">
            <div className="flex -space-x-1.5" aria-hidden>
              {item.members_preview.map((m, i) => (
                <Avatar key={`${m.display_name}-${i}`} url={m.avatar_url} name={m.display_name} size={26} className="ring-2 ring-surface" />
              ))}
            </div>
            <span className="text-sm font-semibold tabular-nums">
              {item.count}/{item.capacity}
            </span>
          </div>
        ) : (
          <span className="text-sm text-muted">Phòng đang được tạo</span>
        )}
        {item.room_id !== null ? (
          <Link href={`/hoi-vien/phong/${item.room_id}`} className={cn(btnLink, "bg-primary text-surface hover:bg-primary-hover")}>
            Vào phòng
          </Link>
        ) : null}
      </div>
    </article>
  );
}

function Row({ item, today }: { item: Upcoming; today: string }) {
  const body = (
    <>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold">
          {dayLabel(item.play_date, today)} · {hourRange(item.start_at, item.end_at)}
        </span>
        <span className="block truncate text-xs text-muted">{item.resource_name}</span>
      </span>
      <HostTag role={item.role} />
      {item.capacity !== null ? (
        <span className="text-sm font-semibold tabular-nums">
          {item.count}/{item.capacity}
        </span>
      ) : null}
      {item.room_id !== null ? <span aria-hidden>›</span> : null}
    </>
  );
  const cls = "flex items-center gap-3 rounded-lg py-3";
  return item.room_id !== null ? (
    <Link href={`/hoi-vien/phong/${item.room_id}`} className={cn(cls, "hover:bg-primary-softer focus-ring")}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}
