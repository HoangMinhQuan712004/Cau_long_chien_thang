"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Avatar } from "@/components/member-area/avatar";
import { PageBanner } from "@/components/member-area/page-banner";
import { Button } from "@/components/ui/button";
import { Dropdown } from "@/components/ui/dropdown";
import { errorText } from "@/lib/api/write";
import { cn } from "@/lib/cn";
import { formatDayMonth, formatLongDate, vnDate } from "@/lib/format";
import { toast } from "@/lib/feedback";
import { usePolling } from "@/hooks/use-polling";
import { api } from "@/lib/api/client";
import { EventCard, type EventCardData } from "./event-card";
import { roomsApi } from "./requests";
import { type RoomCard, type RoomList, MAX_MEMBERS } from "./types";
import { dmy, hourRange, joinBlockText, seatsText, tierRangeText } from "./utils";

// /hoi-vien/danh-sach-san (T-017 AC4–AC6, T-054): banner 3 số, lọc Tất cả / Sân của tôi + khung giờ, tìm theo đúng mã booking,
// mỗi khung giờ một hàng thẻ phòng cuộn ngang.

// Trường mới của T-054; bỏ kiểu này sau khi merge BE và sinh lại schema.d.ts
type Room = RoomCard & { play_date?: string; status?: string };
type RoomGroup = { key: string; state: "ongoing" | "upcoming" | "ended"; label: string; rooms: Room[] };

const WEEKDAY = ["CN", "T2", "T3", "T4", "T5", "T6", "T7"];
const isEnded = (r: Room) => r.status === "ended";

/** Nhóm theo ngày + khung giờ (dữ liệu đã sắp theo giờ); ngày khác `today` thì tiêu đề có ngày: "T7 08/11 · 15h–16h". */
function groupRooms(rooms: Room[], today: string | undefined): RoomGroup[] {
  const out: RoomGroup[] = [];
  for (const r of rooms) {
    const key = `${r.start_at}|${r.end_at}`;
    let g = out.find((x) => x.key === key);
    if (!g) {
      const day = r.play_date ?? vnDate(r.start_at);
      const prefix = day === today ? "" : `${WEEKDAY[new Date(`${day}T00:00:00Z`).getUTCDay()]} ${formatDayMonth(day)} · `;
      g = { key, state: isEnded(r) ? "ended" : r.phase === "ongoing" ? "ongoing" : "upcoming", label: `${prefix}${hourRange(r.start_at, r.end_at)}`, rooms: [] };
      out.push(g);
    }
    g.rooms.push(r);
  }
  return out;
}

const STATE_LABEL: Record<RoomGroup["state"], string> = { ongoing: "Đang diễn ra", upcoming: "Sắp diễn ra", ended: "Đã kết thúc" };

export function RoomsScreen() {
  const [data, setData] = useState<RoomList | null>(null);
  const [error, setError] = useState("");
  // ?loc=cua-toi (từ "Xem tất cả" ở Tổng quan) mở sẵn bộ lọc "Sân của tôi"
  const [scope, setScope] = useState<"all" | "mine" | "events">(initialScope(useSearchParams().get("loc")));
  // Sự kiện 14 ngày tới (T-045); tải một lần khi vào trang, tải lại khi mở tab Sự kiện
  const [events, setEvents] = useState<EventCardData[] | null>(null);
  const [eventsFailed, setEventsFailed] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  // Lọc khung giờ: chỉ phòng hôm nay, lọc ngay trên dữ liệu đã có
  const [slot, setSlot] = useState("");
  // Tìm theo mã booking: tìm khi Enter / bấm Tìm; bỏ qua tab và lọc giờ. `items: null` = đang tìm
  const searchId = useId();
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState<{ q: string; items: Room[] | null; error: string } | null>(null);
  const searchSeq = useRef(0);

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

  async function runSearch(q: string) {
    const mine = ++searchSeq.current; // chỉ nhận kết quả của lần tìm mới nhất
    setSearch((cur) => ({ q, items: cur?.q === q ? cur.items : null, error: "" }));
    const res = await roomsApi.searchRooms(q);
    if (mine !== searchSeq.current) return;
    if (res.ok) setSearch({ q, items: res.data.items, error: "" });
    else if (res.error.status === 401) window.location.replace(`/dang-nhap?next=${encodeURIComponent("/hoi-vien/danh-sach-san")}&ly-do=het-han`);
    else setSearch({ q, items: [], error: res.error.status === 429 ? "Bạn tìm quá nhiều lần. Vui lòng thử lại sau ít phút." : errorText(res.error) });
  }
  function clearSearch() {
    searchSeq.current += 1; // bỏ kết quả của lượt tìm đang chạy
    setSearch(null);
    setQuery("");
  }

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
    if (search) await runSearch(search.q);
  }

  const rooms = useMemo(() => (data ? data.items.filter((r) => scope === "all" || r.is_mine) : []), [data, scope]);
  const groups = useMemo(() => groupRooms(rooms, data?.date), [rooms, data?.date]);
  const searchGroups = useMemo(() => groupRooms(search?.items ?? [], data?.date), [search?.items, data?.date]);
  // Khung đang chọn không còn ở tab này (đổi tab, phòng vừa đóng) ⇒ về "Tất cả"
  const slotOn = groups.some((g) => g.key === slot) ? slot : "";
  const shownGroups = slotOn ? groups.filter((g) => g.key === slotOn) : groups;
  const roomRows = (list: RoomGroup[]) =>
    list.map((g) => <RoomRow key={g.key} group={g} busyId={busyId} onAct={(r, k) => void act(r, k)} />);

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
              onClick={() => {
                setScope(k);
                clearSearch();
              }}
              className={cn("h-11 shrink-0 rounded-full border px-5 text-sm font-semibold whitespace-nowrap focus-ring sm:h-10", scope === k ? "border-primary-hover bg-primary-hover text-surface" : "border-border-strong bg-surface hover:bg-primary-softer")}
            >
              {label}
            </button>
          ))}
        </div>

        {scope !== "events" ? (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {!search && groups.length > 0 ? (
              <Dropdown
                aria-label="Lọc theo khung giờ"
                value={slotOn}
                onChange={setSlot}
                options={[{ value: "", label: "Tất cả" }, ...groups.map((g) => ({ value: g.key, label: g.label }))]}
                renderValue={(o) => `Khung giờ: ${o?.label ?? "Tất cả"}`}
                className="w-full sm:w-56"
              />
            ) : null}
            <form
              role="search"
              className="flex w-full min-w-0 gap-2 sm:ml-auto sm:w-auto"
              onSubmit={(e) => {
                e.preventDefault();
                const q = query.replace(/\s+/g, "").toUpperCase();
                if (q) void runSearch(q);
                else clearSearch();
              }}
            >
              <label htmlFor={searchId} className="sr-only">
                Tìm theo mã booking
              </label>
              <input
                id={searchId}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                maxLength={40}
                autoComplete="off"
                placeholder="Tìm theo mã booking"
                className="h-11 min-w-0 flex-1 rounded-lg border border-border-strong bg-surface px-3 text-sm focus-ring sm:w-64 sm:flex-none"
              />
              <Button type="submit" variant="secondary" className="h-11 sm:h-11">
                Tìm
              </Button>
              {search ? (
                <Button type="button" variant="secondary" className="h-11 sm:h-11" onClick={clearSearch}>
                  Xóa
                </Button>
              ) : null}
            </form>
          </div>
        ) : null}

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
        ) : search ? (
          search.error ? (
            <div role="alert" className="mt-6 rounded-card bg-surface p-8 text-center shadow-card">
              <p className="font-semibold">{search.error}</p>
              <Button className="mt-4" onClick={() => void runSearch(search.q)}>
                Thử lại
              </Button>
            </div>
          ) : !search.items ? (
            <p className="mt-10 text-center text-muted" aria-busy>
              Đang tìm…
            </p>
          ) : searchGroups.length === 0 ? (
            <p role="status" className="mt-6 rounded-card bg-surface p-8 text-center text-muted shadow-card">
              Không tìm thấy phòng có mã này. Hãy nhập đủ mã, ví dụ BK-20261106-001.
            </p>
          ) : (
            roomRows(searchGroups)
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
          roomRows(shownGroups)
        )}
      </div>
    </>
  );
}

/**
 * Một khung giờ: tiêu đề + một hàng thẻ cuộn ngang, thẻ cuối hé ở cạnh phải để biết còn phòng.
 * Điện thoại: tràn sát mép, có snap. Máy tính: vùng cuộn focus được nên dùng được phím mũi tên.
 */
function RoomRow({ group: g, busyId, onAct }: { group: RoomGroup; busyId: number | null; onAct: (r: RoomCard, k: "request" | "cancel" | "accept" | "decline") => void }) {
  const title = `${STATE_LABEL[g.state]} · ${g.label}`;
  return (
    <section className="mt-6" aria-label={title}>
      <h2 className="flex items-center gap-2 text-sm font-semibold text-muted">
        <span aria-hidden className={cn("size-2 rounded-full", g.state === "ongoing" ? "bg-primary" : g.state === "ended" ? "bg-subtle" : "border border-subtle")} />
        {title}
        <span aria-hidden className="h-px flex-1 bg-border" />
      </h2>
      <div role="group" tabIndex={0} aria-label={`Các phòng ${g.label}`} className="-mx-4 mt-3 flex snap-x snap-mandatory scroll-px-4 gap-4 overflow-x-auto px-4 pb-2 focus-ring sm:mx-0 sm:snap-none sm:px-0">
        {g.rooms.map((r) => (
          <div key={r.id} className="flex w-[85%] max-w-80 shrink-0 snap-start sm:w-72">
            <RoomCardView r={r} busy={busyId === r.id} onAct={(k) => onAct(r, k)} />
          </div>
        ))}
      </div>
    </section>
  );
}

function Crown() {
  return (
    <svg viewBox="0 0 20 20" className="size-4 text-accent" fill="currentColor" aria-hidden>
      <path d="m3 6 3.5 3L10 4l3.5 5L17 6l-1.5 9h-11z" />
    </svg>
  );
}

function RoomCardView({ r, busy, onAct }: { r: Room; busy: boolean; onAct: (k: "request" | "cancel" | "accept" | "decline") => void }) {
  const full = r.member_count >= MAX_MEMBERS;
  const mine = r.is_mine;
  const ended = isEnded(r);
  const ongoing = !ended && r.phase === "ongoing";
  const shown = r.members.slice(0, 7);
  const extra = r.member_count - shown.length;
  const cta = "inline-flex h-11 flex-1 items-center justify-center rounded-lg bg-cta px-4 text-sm font-bold tracking-wide text-cta-fg uppercase hover:bg-cta-hover focus-ring";
  return (
    <article className={cn("w-full overflow-hidden rounded-xl border bg-surface shadow-card", mine ? "border-primary/40 ring-1 ring-primary/20" : "border-border", full && !mine && "opacity-85")}>
      {/* Dải trạng thái: pill Đang diễn ra (vàng) / Sắp diễn ra */}
      <div className="flex items-center justify-between gap-2 bg-appbar px-4 py-2.5 text-surface">
        <span className={cn("rounded-full px-2.5 py-0.5 text-xs font-bold", ongoing ? "bg-cta text-cta-fg" : "bg-surface/15 text-surface")}>{ended ? STATE_LABEL.ended : ongoing ? STATE_LABEL.ongoing : STATE_LABEL.upcoming}</span>
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
          {ended ? (
            // Phòng đã đóng: chỉ xem, không xin vào được
            <Link href={`/hoi-vien/phong/${r.id}`} className="inline-flex h-11 flex-1 items-center justify-center rounded-lg border border-primary px-4 text-sm font-semibold hover:bg-primary-softer focus-ring">
              Xem phòng
            </Link>
          ) : mine ? (
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
      {!ended && !mine && r.my_invite_id === null && !r.my_join_pending && !full && r.my_join_block ? (
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
