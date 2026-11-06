"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Avatar } from "@/components/member-area/avatar";
import { PageBanner } from "@/components/member-area/page-banner";
import { Button } from "@/components/ui/button";
import { errorText } from "@/lib/api/write";
import { cn } from "@/lib/cn";
import { formatLongDate } from "@/lib/format";
import { toast } from "@/lib/feedback";
import { usePolling } from "@/hooks/use-polling";
import { api } from "@/lib/api/client";
import { EventCard, type EventCardData } from "./event-card";
import { roomsApi } from "./requests";
import { type RoomCard, type RoomList, MAX_MEMBERS } from "./types";
import { dmy, hourRange, joinBlockText, seatsText, tierRangeText } from "./utils";

// /hoi-vien/danh-sach-san (T-017 AC4–AC6): banner 3 số, lọc Tất cả / Sân của tôi, nhóm theo khung giờ, thẻ phòng.

export function RoomsScreen() {
  const [data, setData] = useState<RoomList | null>(null);
  const [error, setError] = useState("");
  // ?loc=cua-toi (từ "Xem tất cả" ở Tổng quan) mở sẵn bộ lọc "Sân của tôi"
  const [scope, setScope] = useState<"all" | "mine" | "events">(initialScope(useSearchParams().get("loc")));
  // Sự kiện 14 ngày tới (T-045); tải một lần khi vào trang, tải lại khi mở tab Sự kiện
  const [events, setEvents] = useState<EventCardData[] | null>(null);
  const [eventsFailed, setEventsFailed] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);

  const apply = useCallback((res: Awaited<ReturnType<typeof roomsApi.listRooms>>) => {
    if (res.ok) {
      setData(res.data);
      setError("");
    } else if (res.error.status === 401) {
      window.location.replace(`/dang-nhap?next=${encodeURIComponent("/hoi-vien/danh-sach-san")}&ly-do=het-han`);
    } else setError("Không tải được danh sách sân. Vui lòng thử lại.");
  }, []);
  const load = useCallback(async () => apply(await roomsApi.listRooms("all")), [apply]);

  useEffect(() => {
    let cancelled = false;
    void roomsApi.listRooms("all").then((res) => !cancelled && apply(res));
    return () => {
      cancelled = true;
    };
  }, [apply]);
  usePolling(() => void load(), 5000);

  const loadEvents = useCallback(async () => {
    try {
      const { data: d, response } = await api.GET("/api/v1/member-area/events", { params: { query: { days: 14 } } });
      if (d) {
        setEvents(d);
        setEventsFailed(false);
      } else if (response.status !== 401) setEventsFailed(true);
    } catch {
      setEventsFailed(true);
    }
  }, []);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải khi vào trang và khi mở tab Sự kiện
    void loadEvents();
  }, [loadEvents, scope]);

  async function act(room: RoomCard, kind: "request" | "cancel" | "accept" | "decline") {
    if (busyId !== null) return;
    setBusyId(room.id);
    const res =
      kind === "request"
        ? await roomsApi.requestJoin(room.id, room.version)
        : kind === "cancel"
          ? await roomsApi.cancelRequest(room.id)
          : await roomsApi.answerInvite(room.my_invite_id ?? 0, kind === "accept");
    setBusyId(null);
    if (!res.ok) toast(errorText(res.error), undefined, "error");
    else if (kind === "request") toast("Đã gửi yêu cầu vào phòng", `${room.resource_name} · Host sẽ duyệt`);
    else if (kind === "accept") toast("Đã vào phòng", room.resource_name);
    await load();
  }

  const rooms = useMemo(() => (data ? data.items.filter((r) => scope === "all" || r.is_mine) : []), [data, scope]);
  // Nhóm theo khung giờ bắt đầu (dữ liệu đã sắp theo giờ)
  const groups = useMemo(() => {
    const out: { key: string; ongoing: boolean; label: string; rooms: RoomCard[] }[] = [];
    for (const r of rooms) {
      const key = `${r.start_at}|${r.end_at}`;
      let g = out.find((x) => x.key === key);
      if (!g) {
        g = { key, ongoing: r.phase === "ongoing", label: hourRange(r.start_at, r.end_at), rooms: [] };
        out.push(g);
      }
      g.rooms.push(r);
    }
    return out;
  }, [rooms]);

  const stat = (n: number | undefined, label: string) => (
    <div className="min-w-24 rounded-lg bg-surface/10 px-4 py-2.5 ring-1 ring-surface/20">
      <p className="text-2xl leading-none font-bold tabular-nums">{n ?? "–"}</p>
      <p className="mt-1 text-xs text-surface/80">{label}</p>
    </div>
  );

  return (
    <>
      <PageBanner
        title="Danh sách sân"
        subtitle={data ? `Các sân và khung giờ đang hoạt động hôm nay · ${dmy(data.date)}` : "Các sân và khung giờ đang hoạt động hôm nay"}
        aside={
          <div className="flex gap-2 sm:gap-3">
            {stat(data?.ongoing_count, "Đang diễn ra")}
            {stat(data?.upcoming_count, "Sắp diễn ra")}
            {stat(data?.mine_count, "Phòng của bạn")}
          </div>
        }
      />
      <div className="mx-auto max-w-6xl px-4 py-6 sm:py-8">
        <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0" role="group" aria-label="Lọc phòng">
          {(
            [
              ["all", `Tất cả (${data?.all_count ?? 0})`],
              ["mine", `Sân của tôi (${data?.mine_count ?? 0})`],
              ["events", `Sự kiện${events ? ` (${events.length})` : ""}`],
            ] as const
          ).map(([k, label]) => (
            <button
              key={k}
              type="button"
              aria-pressed={scope === k}
              onClick={() => setScope(k)}
              className={cn("h-11 shrink-0 rounded-full border px-5 text-sm font-semibold whitespace-nowrap focus-ring sm:h-10", scope === k ? "border-primary-hover bg-primary-hover text-surface" : "border-border-strong bg-surface hover:bg-primary-softer")}
            >
              {label}
            </button>
          ))}
        </div>

        {scope === "events" ? (
          eventsFailed && !events ? (
            <div role="alert" className="mt-6 rounded-card bg-surface p-8 text-center shadow-card">
              <p className="font-semibold">Không tải được sự kiện. Vui lòng thử lại.</p>
              <Button className="mt-4" onClick={() => void loadEvents()}>
                Thử lại
              </Button>
            </div>
          ) : !events ? (
            <p className="mt-10 text-center text-muted" aria-busy>
              Đang tải…
            </p>
          ) : events.length === 0 ? (
            <p className="mt-10 rounded-card bg-surface p-8 text-center text-muted shadow-card">Chưa có sự kiện sắp tới</p>
          ) : (
            eventDays(events).map((g) => (
              <section key={g.date} className="mt-6" aria-label={formatLongDate(g.date)}>
                <h2 className="flex items-center gap-2 text-sm font-semibold text-muted">
                  {formatLongDate(g.date)}
                  <span aria-hidden className="h-px flex-1 bg-border" />
                </h2>
                <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {g.items.map((e) => (
                    <EventCard key={e.code} e={e} />
                  ))}
                </div>
              </section>
            ))
          )
        ) : error && !data ? (
          <div role="alert" className="mt-6 rounded-card bg-surface p-8 text-center shadow-card">
            <p className="font-semibold">{error}</p>
            <Button className="mt-4" onClick={() => void load()}>
              Thử lại
            </Button>
          </div>
        ) : !data ? (
          <p className="mt-10 text-center text-muted" aria-busy>
            Đang tải…
          </p>
        ) : groups.length === 0 ? (
          <p className="mt-10 rounded-card bg-surface p-8 text-center text-muted shadow-card">
            {scope === "mine" ? "Bạn chưa ở phòng nào hôm nay." : "Hôm nay chưa có phòng nào đang mở."}
          </p>
        ) : (
          groups.map((g) => (
            <section key={g.key} className="mt-6" aria-label={`${g.ongoing ? "Đang diễn ra" : "Sắp diễn ra"} ${g.label}`}>
              <h2 className="flex items-center gap-2 text-sm font-semibold text-muted">
                <span aria-hidden className={cn("size-2 rounded-full", g.ongoing ? "bg-primary" : "border border-subtle")} />
                {g.ongoing ? "Đang diễn ra" : "Sắp diễn ra"} · {g.label}
                <span aria-hidden className="h-px flex-1 bg-border" />
              </h2>
              <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {g.rooms.map((r) => (
                  <RoomCardView key={r.id} r={r} busy={busyId === r.id} onAct={(k) => void act(r, k)} />
                ))}
              </div>
            </section>
          ))
        )}
      </div>
    </>
  );
}

function Crown() {
  return (
    <svg viewBox="0 0 20 20" className="size-4 text-accent" fill="currentColor" aria-hidden>
      <path d="m3 6 3.5 3L10 4l3.5 5L17 6l-1.5 9h-11z" />
    </svg>
  );
}

function RoomCardView({ r, busy, onAct }: { r: RoomCard; busy: boolean; onAct: (k: "request" | "cancel" | "accept" | "decline") => void }) {
  const full = r.member_count >= MAX_MEMBERS;
  const mine = r.is_mine;
  const ongoing = r.phase === "ongoing";
  const shown = r.members.slice(0, 7);
  const extra = r.member_count - shown.length;
  const cta = "inline-flex h-11 flex-1 items-center justify-center rounded-lg bg-cta px-4 text-sm font-bold tracking-wide text-cta-fg uppercase hover:bg-cta-hover focus-ring";
  return (
    <article className={cn("overflow-hidden rounded-xl border bg-surface shadow-card", mine ? "border-primary/40 ring-1 ring-primary/20" : "border-border", full && !mine && "opacity-85")}>
      {/* Dải trạng thái: pill Đang diễn ra (vàng) / Sắp diễn ra */}
      <div className="flex items-center justify-between gap-2 bg-appbar px-4 py-2.5 text-surface">
        <span className={cn("rounded-full px-2.5 py-0.5 text-xs font-bold", ongoing ? "bg-cta text-cta-fg" : "bg-surface/15 text-surface")}>{ongoing ? "Đang diễn ra" : "Sắp diễn ra"}</span>
        <span className="text-sm font-semibold tabular-nums">{hourRange(r.start_at, r.end_at)}</span>
      </div>
      <div className="p-4">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h3 className="text-lg leading-tight font-bold">{r.resource_name}</h3>
            <p className="text-xs text-muted">{r.resource_type_name}</p>
            {/* Khoảng hạng người đặt chọn lúc đặt sân; không đặt thì vẫn hiện để biết phòng không giới hạn hạng */}
            <span className={cn("mt-1.5 inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1", tierRangeText(r.tier_range) ? "bg-primary-softer text-primary ring-primary/25" : "bg-background text-muted ring-border")}>{tierRangeText(r.tier_range) ?? "Không có hạng"}</span>
          </div>
          {mine ? <span className="rounded-full bg-primary-softer px-2.5 py-0.5 text-xs font-semibold text-primary ring-1 ring-primary/25">Bạn</span> : null}
        </div>
        <p className="mt-3 flex items-center gap-1.5 text-sm">
          <Crown />
          <span>
            Host: <b className="font-semibold">{r.host.display_name}</b>
          </span>
        </p>
        <div className="mt-3 flex items-center justify-between gap-2">
          <div className="flex -space-x-1.5" aria-hidden>
            {shown.map((m, i) => (
              <Avatar key={`${m.display_name}-${i}`} url={m.avatar_url} name={m.display_name} size={28} className="ring-2 ring-surface" />
            ))}
            {extra > 0 ? <span className="grid size-7 place-items-center rounded-full bg-border text-xs font-semibold ring-2 ring-surface">+{extra}</span> : null}
          </div>
          <span className="text-sm font-bold tabular-nums">
            {r.member_count}/{MAX_MEMBERS}
          </span>
        </div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-border" role="progressbar" aria-valuemin={0} aria-valuemax={MAX_MEMBERS} aria-valuenow={r.member_count} aria-label="Số người trong phòng">
          <div className={cn("h-full rounded-full", full ? "bg-subtle" : "bg-linear-to-r from-primary-hover to-primary")} style={{ width: `${(r.member_count / MAX_MEMBERS) * 100}%` }} />
        </div>
        <p className="mt-1 text-xs text-muted">{seatsText(r.member_count)}</p>

        <div className="mt-4 flex gap-2">
          {mine ? (
            <Link href={`/hoi-vien/phong/${r.id}`} className={cta}>
              Vào phòng
            </Link>
          ) : r.my_invite_id !== null ? (
            <>
              <Button variant="cta" block className="flex-1" onClick={() => onAct("accept")} loading={busy} disabled={full}>
                Nhận lời mời
              </Button>
              <Button variant="secondary" className="h-11 sm:h-11" onClick={() => onAct("decline")} disabled={busy}>
                Từ chối
              </Button>
            </>
          ) : r.my_join_pending ? (
            <Button variant="secondary" block className="flex-1" onClick={() => onAct("cancel")} loading={busy} title="Bấm để hủy yêu cầu">
              Đã xin vào
            </Button>
          ) : full ? (
            <Button variant="secondary" block className="flex-1" disabled>
              Đã đủ
            </Button>
          ) : (
            <Button variant="secondary" block className="flex-1" onClick={() => onAct("request")} loading={busy} disabled={Boolean(r.my_join_block)} title={joinBlockText(r.my_join_block) ?? undefined}>
              Xin vào
            </Button>
          )}
        </div>
      </div>
      {!mine && r.my_invite_id === null && !r.my_join_pending && !full && r.my_join_block ? (
        <p role="note" className="mt-2 text-xs text-muted">
          {joinBlockText(r.my_join_block)}
        </p>
      ) : null}
    </article>
  );
}

/** Nhóm sự kiện theo ngày diễn ra (mảng BE đã sắp theo giờ bắt đầu). */
function eventDays(events: EventCardData[]) {
  const out: { date: string; items: EventCardData[] }[] = [];
  for (const e of events) {
    const g = out.find((x) => x.date === e.play_date);
    if (g) g.items.push(e);
    else out.push({ date: e.play_date, items: [e] });
  }
  return out;
}

/** `?loc=cua-toi` (từ "Xem tất cả" ở lịch sắp tới) / `?loc=su-kien` (từ khối Sự kiện ở Tổng quan) mở sẵn bộ lọc tương ứng. */
const initialScope = (loc: string | null): "all" | "mine" | "events" => (loc === "cua-toi" ? "mine" : loc === "su-kien" ? "events" : "all");
