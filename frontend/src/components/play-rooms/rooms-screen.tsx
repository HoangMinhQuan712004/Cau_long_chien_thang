"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Avatar } from "@/components/member-area/avatar";
import { PageBanner } from "@/components/member-area/page-banner";
import { Button } from "@/components/ui/button";
import { errorText } from "@/lib/api/write";
import { cn } from "@/lib/cn";
import { toast } from "@/lib/feedback";
import { usePolling } from "@/hooks/use-polling";
import { roomsApi } from "./requests";
import { type RoomCard, type RoomList, MAX_MEMBERS } from "./types";
import { dmy, hourRange, seatsText } from "./utils";

// /hoi-vien/danh-sach-san (T-017 AC4–AC6): banner 3 số, lọc Tất cả / Sân của tôi, nhóm theo khung giờ, thẻ phòng.

export function RoomsScreen() {
  const [data, setData] = useState<RoomList | null>(null);
  const [error, setError] = useState("");
  const [scope, setScope] = useState<"all" | "mine">("all");
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
        <div className="flex flex-wrap gap-2" role="group" aria-label="Lọc phòng">
          {(
            [
              ["all", `Tất cả (${data?.all_count ?? 0})`],
              ["mine", `Sân của tôi (${data?.mine_count ?? 0})`],
            ] as const
          ).map(([k, label]) => (
            <button
              key={k}
              type="button"
              aria-pressed={scope === k}
              onClick={() => setScope(k)}
              className={cn("h-9 rounded-full border px-4 text-sm font-medium focus-ring", scope === k ? "border-primary-hover bg-primary-hover text-surface" : "border-border-strong bg-surface hover:bg-primary-softer")}
            >
              {label}
            </button>
          ))}
        </div>

        {error && !data ? (
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
              <h2 className="flex items-center gap-2 text-xs font-semibold tracking-wide text-muted uppercase">
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
  const shown = r.members.slice(0, 7);
  const extra = r.member_count - shown.length;
  return (
    <article className={cn("rounded-card border p-4 shadow-card", mine ? "border-primary/25 bg-primary-softer" : "border-border bg-surface", full && !mine && "opacity-80")}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-base font-bold">{r.resource_name}</h3>
          <p className="text-xs text-muted">
            {r.resource_type_name} · {hourRange(r.start_at, r.end_at)}
          </p>
        </div>
        {mine ? <span className="rounded-full bg-surface px-2.5 py-0.5 text-xs font-semibold ring-1 ring-border">Bạn</span> : null}
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
            <Avatar key={`${m.display_name}-${i}`} url={m.avatar_url} name={m.display_name} size={26} className="ring-2 ring-surface" />
          ))}
          {extra > 0 ? <span className="grid size-[26px] place-items-center rounded-full bg-border text-xs font-semibold ring-2 ring-surface">+{extra}</span> : null}
        </div>
        <span className="text-sm font-semibold tabular-nums">
          {r.member_count}/{MAX_MEMBERS}
        </span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-border" role="progressbar" aria-valuemin={0} aria-valuemax={MAX_MEMBERS} aria-valuenow={r.member_count} aria-label="Số người trong phòng">
        <div className={cn("h-full rounded-full", full ? "bg-subtle" : "bg-primary")} style={{ width: `${(r.member_count / MAX_MEMBERS) * 100}%` }} />
      </div>
      <p className="mt-1 text-xs text-muted">{seatsText(r.member_count)}</p>

      <div className="mt-4 flex gap-2">
        {mine ? (
          <Link href={`/hoi-vien/phong/${r.id}`} className="inline-flex h-10 flex-1 items-center justify-center rounded-lg bg-primary px-4 text-sm font-semibold text-surface hover:bg-primary-hover focus-ring">
            Vào phòng
          </Link>
        ) : r.my_invite_id !== null ? (
          <>
            <Button className="flex-1" onClick={() => onAct("accept")} loading={busy} disabled={full}>
              Nhận lời mời
            </Button>
            <Button variant="secondary" onClick={() => onAct("decline")} disabled={busy}>
              Từ chối
            </Button>
          </>
        ) : r.my_join_pending ? (
          <Button variant="secondary" className="flex-1" onClick={() => onAct("cancel")} loading={busy} title="Bấm để hủy yêu cầu">
            Đã xin vào
          </Button>
        ) : full ? (
          <Button variant="secondary" className="flex-1" disabled>
            Đã đủ
          </Button>
        ) : (
          <Button variant="secondary" className="flex-1" onClick={() => onAct("request")} loading={busy}>
            Xin vào
          </Button>
        )}
      </div>
    </article>
  );
}
