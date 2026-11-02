"use client";

/* eslint-disable react-hooks/refs -- các hàm xử lý sự kiện (kéo thả, ghi lệnh) đọc `versionRef`; chỉ chạy khi có sự kiện, không chạy lúc render */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Avatar } from "@/components/member-area/avatar";
import { PageBanner } from "@/components/member-area/page-banner";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { errorText, type WriteResult } from "@/lib/api/write";
import { cn } from "@/lib/cn";
import { toast } from "@/lib/feedback";
import { formatTime } from "@/lib/format";
import { usePolling } from "@/hooks/use-polling";
import { ConfirmDialog } from "./confirm-dialog";
import { Court, type CourtEditor, type EditorPlayer } from "./court";
import { type Draft, fromMatch, idsOf, isFull, place, remove, sameLineup, type SlotRef, swap, switchTeam } from "./lineup";
import { type DragSource, type DropTarget, useLineupDrag } from "./lineup-drag";
import { InviteDialog, ResultDialog } from "./room-dialogs";
import { RoomHistory } from "./room-history";
import { roomsApi } from "./requests";
import { SlotDialog, type SlotDialogState } from "./slot-dialog";
import { type Format, FORMAT_LABEL, FORMAT_NEED, MAX_MEMBERS, type RoomDetail, type RoomMember } from "./types";
import { hourRange, MATCHES_READY } from "./utils";

// /hoi-vien/phong/[id] (T-017 AC8–AC20): sân vẽ, hàng chờ, nút theo vai, popup xác nhận, Lịch sử trận / Xếp hạng.

type Dialog = null | { kind: "kick" | "transfer"; m: RoomMember } | { kind: "invite" } | { kind: "result" } | { kind: "leave" };

/** Đội hình đang hiển thị cho Host: bản nháp (nếu còn hợp lệ) hoặc đội hình đã lưu trên server (trận `drawn`). */
function deriveLineup(room: RoomDetail | null, draft: Draft | null) {
  if (!room) return null;
  const cur = room.current_match;
  const playing = cur?.status === "playing";
  const memberIds = new Set(room.members.map((m) => m.id));
  const server = fromMatch(room.format, cur);
  // Bỏ bản nháp khi đổi thể thức, có người rời phòng hoặc trận đã bắt đầu
  const valid = draft !== null && draft.format === room.format && !playing && idsOf(draft).every((id) => memberIds.has(id));
  return {
    server,
    base: valid && draft ? draft : server,
    hasDraft: valid,
    editable: room.my_role === "host" && room.status === "open" && !playing && MATCHES_READY,
  };
}

function Crown({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 20 20" className={cn("size-4 text-accent", className)} fill="currentColor" aria-hidden>
      <path d="m3 6 3.5 3L10 4l3.5 5L17 6l-1.5 9h-11z" />
    </svg>
  );
}

export function RoomScreen({ id, initialTab = "play" }: { id: number; initialTab?: "play" | "history" }) {
  const router = useRouter();
  const [room, setRoom] = useState<RoomDetail | null>(null);
  const [problem, setProblem] = useState<"" | "notfound" | "error">("");
  const [tab, setTab] = useState<"play" | "history">(initialTab);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [busy, setBusy] = useState(false);
  const versionRef = useRef(0);
  // Đội hình Host đang xếp (T-027): bản nháp trên máy; đủ người mới gửi lên server
  const [draft, setDraft] = useState<Draft | null>(null);
  const [slotDlg, setSlotDlg] = useState<SlotDialogState | null>(null);
  // Mốc thời gian lúc tải gần nhất (để so với giờ cho phép bắt đầu trận, không đọc đồng hồ khi render)
  const [nowMs, setNowMs] = useState(0);

  const apply = useCallback(
    (res: Awaited<ReturnType<typeof roomsApi.getRoom>>) => {
      if (res.ok) {
        versionRef.current = res.data.version;
        setNowMs(Date.now());
        setRoom(res.data);
        setProblem("");
      } else if (res.error.status === 401) {
        window.location.replace(`/dang-nhap?next=${encodeURIComponent(`/hoi-vien/phong/${id}`)}&ly-do=het-han`);
      } else if (res.error.status === 404 || res.error.status === 403) setProblem("notfound");
      else setProblem((p) => p || "error");
    },
    [id],
  );
  const load = useCallback(async () => apply(await roomsApi.getRoom(id)), [apply, id]);

  useEffect(() => {
    let cancelled = false;
    void roomsApi.getRoom(id).then((res) => !cancelled && apply(res));
    return () => {
      cancelled = true;
    };
  }, [id, apply]);
  usePolling(() => void load(), 5000);

  /**
   * Gửi một lệnh ghi kèm version phòng. Phòng vừa đổi (E-ROOM-6) / đã đóng (E-ROOM-1): báo, tải lại, coi như xong.
   * Trả `{ done }` (true khi lệnh thật sự được áp dụng) và `error` để hiện trong hộp thoại.
   */
  async function write(fn: (version: number) => Promise<WriteResult<unknown>>): Promise<{ done: boolean; error: string | null }> {
    const res = await fn(versionRef.current);
    if (!res.ok) {
      const code = res.error.code;
      if (code === "E-ROOM-6" || code === "E-ROOM-1") {
        toast(res.error.message, undefined, "info");
        await load();
        return { done: false, error: null };
      }
      return { done: false, error: errorText(res.error) };
    }
    await load();
    return { done: true, error: null };
  }

  /** Sửa đội hình: đủ người thì gửi lên server (tạo / thay trận `drawn`), chưa đủ thì giữ bản nháp. */
  function editLineup(fn: (d: Draft) => Draft) {
    const lu = deriveLineup(room, draft);
    if (!lu || !lu.editable || busy) return;
    const next = fn(lu.base);
    if (!isFull(next)) return setDraft(next);
    if (!lu.hasDraft && sameLineup(next, lu.server)) return;
    void sendLineup(next);
  }

  async function sendLineup(next: Draft) {
    setDraft(next);
    setBusy(true);
    const a = next.a as number[];
    const b = next.b as number[];
    let r = await write((v) => roomsApi.setLineup(id, a, b, v));
    // Phòng vừa đổi (E-ROOM-6): `write` đã tải lại, gửi lại đúng đội hình một lần với version mới
    if (!r.done && !r.error) r = await write((v) => roomsApi.setLineup(id, a, b, v));
    setBusy(false);
    if (r.done) setDraft(null);
    else if (r.error) toast(r.error, undefined, "error");
  }

  function handleDrop(src: DragSource, target: DropTarget, inCourt: boolean) {
    if (src.kind === "member") {
      if (target) editLineup((d) => place(d, src.id, target));
    } else if (target) editLineup((d) => swap(d, src.ref, target));
    else if (!inCourt) editLineup((d) => remove(d, src.ref)); // kéo ra ngoài sân = bỏ khỏi ô
  }
  const drag = useLineupDrag(handleDrop);

  /** Nút nằm ngoài hộp thoại: lỗi hiện bằng toast. */
  async function inline(fn: (version: number) => Promise<WriteResult<unknown>>, ok?: [string, string?]) {
    if (busy) return;
    setBusy(true);
    const r = await write(fn);
    setBusy(false);
    if (r.error) toast(r.error, undefined, "error");
    else if (r.done && ok) toast(ok[0], ok[1]);
  }

  if (problem === "notfound" || (problem === "error" && !room)) {
    return (
      <div className="mx-auto max-w-md px-4 py-20 text-center" role="alert">
        <p className="font-semibold">{problem === "notfound" ? "Phòng này không còn xem được." : "Không tải được phòng. Vui lòng thử lại."}</p>
        <div className="mt-4 flex justify-center gap-3">
          {problem === "error" ? <Button onClick={() => void load()}>Thử lại</Button> : null}
          <Link href="/hoi-vien/danh-sach-san" className="inline-flex h-11 items-center rounded-lg border border-primary px-4 text-sm font-semibold text-primary sm:h-9.5">
            Về Danh sách sân
          </Link>
        </div>
      </div>
    );
  }
  if (!room) {
    return (
      <p className="py-20 text-center text-muted" aria-busy>
        Đang tải…
      </p>
    );
  }

  const open = room.status === "open";
  const isHost = room.my_role === "host" && open;
  const isMember = room.my_role !== "outsider";
  const hostMemberId = room.members.find((m) => m.role === "host")?.id ?? -1;
  const hostName = room.members.find((m) => m.role === "host")?.display_name ?? "";
  const cur = room.current_match;
  const playing = cur?.status === "playing";
  const drawn = cur?.status === "drawn";
  const need = FORMAT_NEED[room.format];
  const waitingAll = room.members.filter((m) => m.queue_state === "waiting");
  const onCourt = new Set([...(cur?.team_a ?? []), ...(cur?.team_b ?? [])].map((p) => p.member_id));
  const waitingShown = waitingAll.filter((m) => !onCourt.has(m.id));
  const lu = deriveLineup(room, draft);
  const lineupIds = new Set(lu ? idsOf(lu.base) : []);
  const editor: CourtEditor | undefined =
    lu?.editable
      ? (() => {
          const person = (mid: number | null): EditorPlayer | null => {
            const m = room.members.find((x) => x.id === mid);
            return m ? { member_id: m.id, display_name: m.display_name, avatar_url: m.avatar_url } : null;
          };
          return {
            a: lu.base.a.map(person),
            b: lu.base.b.map(person),
            over: drag.over,
            onSlot: (ref: SlotRef) => setSlotDlg({ kind: "slot", ref }),
            onRemove: (ref: SlotRef) => editLineup((d) => remove(d, ref)),
            onDragStart: (e, ref, label) => drag.begin(e, { kind: "slot", ref }, label),
          };
        })()
      : undefined;
  const editWaiting = editor ? waitingAll.filter((m) => !lineupIds.has(m.id)) : waitingShown;
  const placedCount = lu ? idsOf(lu.base).length : 0;
  const roomName = room.resource_name.replace(/^Sân (\d+)/, "Sân số $1");
  const beforeStart = nowMs < Date.parse(room.can_start_from);

  async function leave(): Promise<string | null> {
    const r = await write((v) => roomsApi.leave(id, v));
    if (r.error) return r.error;
    if (r.done) {
      toast("Đã rời phòng", roomName);
      router.push("/hoi-vien/danh-sach-san");
    } else setDialog(null); // phòng vừa đổi (E-ROOM-6): đã tải lại, bấm Rời phòng lại nếu vẫn muốn
    return null;
  }

  return (
    <>
      <PageBanner
        title={`Phòng: ${roomName}`}
        subtitle={`${room.members.length}/${MAX_MEMBERS} thành viên · Host: ${hostName} · ${hourRange(room.start_at, room.end_at)}`}
        aside={
          isMember && open ? (
            <button type="button" onClick={() => setDialog({ kind: "leave" })} className="h-10 rounded-lg bg-surface px-4 text-sm font-semibold text-danger hover:bg-primary-softer focus-ring">
              Rời phòng
            </button>
          ) : null
        }
      >
        <div className="relative mx-auto flex max-w-6xl gap-1 px-4" role="tablist" aria-label="Phòng" hidden={!MATCHES_READY}>
          {(
            [
              ["play", "Phòng chơi"],
              ["history", "Lịch sử trận đấu"],
            ] as const
          ).map(([k, label]) => (
            <button
              key={k}
              type="button"
              role="tab"
              aria-selected={tab === k}
              onClick={() => setTab(k)}
              className={cn("-mb-px border-b-2 px-4 py-3 text-sm font-medium focus-ring", tab === k ? "border-surface font-bold text-surface" : "border-transparent text-surface/70 hover:text-surface")}
            >
              {label}
            </button>
          ))}
        </div>
      </PageBanner>

      <div className="mx-auto max-w-6xl space-y-4 px-4 py-6 sm:py-8">
        {!open ? <Alert variant="info">Phòng đã đóng. Bạn chỉ xem được thành viên và kết quả các trận.</Alert> : null}

        {!isMember && open ? (
          <section className="flex flex-wrap items-center justify-between gap-3 rounded-card bg-surface p-4 shadow-card" aria-label="Vào phòng">
            <p className="text-sm">
              {room.my_invite_id !== null
                ? "Bạn được mời vào phòng này."
                : room.my_join_pending
                  ? "Bạn đã gửi yêu cầu vào phòng. Chờ Host duyệt."
                  : room.members.length >= MAX_MEMBERS
                    ? "Phòng đã đủ 8 người."
                    : "Bạn chưa ở trong phòng này."}
            </p>
            <div className="flex gap-2">
              {room.my_invite_id !== null ? (
                <>
                  <Button onClick={() => void inline(() => roomsApi.answerInvite(room.my_invite_id ?? 0, true), ["Đã vào phòng", roomName])} loading={busy} disabled={room.members.length >= MAX_MEMBERS}>
                    Nhận lời mời
                  </Button>
                  <Button variant="secondary" onClick={() => void inline(() => roomsApi.answerInvite(room.my_invite_id ?? 0, false))} disabled={busy}>
                    Từ chối
                  </Button>
                </>
              ) : room.my_join_pending ? (
                <Button variant="secondary" onClick={() => void inline(() => roomsApi.cancelRequest(id))} loading={busy}>
                  Hủy yêu cầu
                </Button>
              ) : (
                <Button variant="secondary" onClick={() => void inline((v) => roomsApi.requestJoin(id, v), ["Đã gửi yêu cầu vào phòng", "Host sẽ duyệt"])} loading={busy} disabled={room.members.length >= MAX_MEMBERS}>
                  Xin vào
                </Button>
              )}
            </div>
          </section>
        ) : null}

        {tab === "history" ? (
          <RoomHistory roomId={id} />
        ) : (
          <>
            <section className="overflow-hidden rounded-card bg-surface shadow-card" aria-label="Điều khiển trận">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-3 p-4" hidden={!MATCHES_READY}>
                <div className="flex items-center gap-3">
                  <span className="text-sm font-semibold text-muted" id="fmt-label">
                    Thể thức
                  </span>
                  <div role="group" aria-labelledby="fmt-label" className="flex rounded-lg border border-border-strong p-0.5">
                    {(["2v2", "1v1"] as Format[]).map((f) => (
                      <button
                        key={f}
                        type="button"
                        aria-pressed={room.format === f}
                        disabled={!isHost || playing || busy}
                        onClick={() => room.format !== f && void inline((v) => roomsApi.setFormat(id, f, v))}
                        className={cn(
                          "h-8 rounded-md px-3.5 text-sm font-semibold focus-ring disabled:cursor-not-allowed",
                          room.format === f ? "bg-primary-hover text-surface" : "text-muted enabled:hover:bg-primary-softer",
                          playing && "opacity-50",
                        )}
                      >
                        {FORMAT_LABEL[f]}
                      </button>
                    ))}
                  </div>
                </div>
                <p className="min-w-0 flex-1 text-sm text-muted" role="status">
                  {playing && cur ? (
                    <span className="inline-flex items-center gap-2 font-medium text-foreground">
                      <span aria-hidden className="size-2 rounded-full bg-danger" />
                      Trận #{cur.no} đang chơi{cur.started_at ? ` · bắt đầu ${formatTime(cur.started_at)}` : ""}
                    </span>
                  ) : isHost && lu?.hasDraft && placedCount < need ? (
                    `Cần đủ ${need} người · đã xếp ${placedCount}/${need} · bản nháp trên máy bạn, chưa lưu`
                  ) : isHost && drawn ? (
                    "Đội hình đã lưu · bấm “Bắt đầu trận” khi sẵn sàng · đổi thể thức sẽ xóa đội hình"
                  ) : drawn ? (
                    "Đổi thể thức sẽ xóa kết quả bốc · chỉ chốt khi bấm “Bắt đầu trận”"
                  ) : isHost && placedCount > 0 ? (
                    `Cần đủ ${need} người · đã xếp ${placedCount}/${need} · bản nháp trên máy bạn, chưa lưu`
                  ) : waitingAll.length >= need ? (
                    `Đủ người · ${Math.min(waitingAll.length, need)}/${need} cho ${FORMAT_LABEL[room.format]}`
                  ) : (
                    `Chưa đủ người · cần ${need} (đang có ${waitingAll.length})`
                  )}
                </p>
                {isHost ? (
                  <div className="flex gap-2">
                    {playing ? (
                      <Button onClick={() => setDialog({ kind: "result" })}>Kết thúc trận</Button>
                    ) : (
                      <>
                        <Button
                          variant="secondary"
                          onClick={() => void inline((v) => roomsApi.draw(id, v)).then(() => setDraft(null))}
                          loading={busy}
                          disabled={waitingAll.length < need}
                        >
                          {drawn ? "Bốc lại" : "Bốc ngẫu nhiên"}
                        </Button>
                        <Button
                          onClick={() => void inline((v) => roomsApi.start(id, v))}
                          loading={busy}
                          disabled={!drawn || Boolean(lu?.hasDraft) || beforeStart}
                          title={!drawn || lu?.hasDraft ? `Cần đủ ${need} người` : beforeStart ? "Chưa tới giờ bắt đầu trận." : undefined}
                        >
                          Bắt đầu trận
                        </Button>
                      </>
                    )}
                  </div>
                ) : null}
              </div>
              <Court
                format={cur?.format ?? room.format}
                teamA={cur?.team_a ?? []}
                teamB={cur?.team_b ?? []}
                hostId={hostMemberId}
                state={playing ? "playing" : drawn || (editor && placedCount > 0) ? "drawn" : "idle"}
                matchNo={cur?.no}
                hint={!MATCHES_READY ? "Bốc cặp và ghi kết quả trận sẽ có ở bản cập nhật sau" : isHost ? "Bấm “Bốc ngẫu nhiên” hoặc kéo / chọn người vào sân" : "Host sẽ bốc ngẫu nhiên để xếp người chơi vào sân"}
                waiting={editWaiting}
                editor={editor}
                onWaitingDrag={editor ? (e, m) => drag.begin(e, { kind: "member", id: m.id }, m.display_name) : undefined}
                onWaitingPick={editor ? (m) => setSlotDlg({ kind: "member", id: m.id }) : undefined}
              />
            </section>

            {isHost && room.join_requests.length > 0 ? (
              <section className="rounded-card bg-surface p-4 shadow-card sm:p-5" aria-labelledby="req-title">
                <h2 id="req-title" className="text-base font-bold">
                  Yêu cầu vào phòng · {room.join_requests.length}
                </h2>
                <ul className="mt-3 divide-y divide-border">
                  {room.join_requests.map((q) => (
                    <li key={q.id} className="flex flex-wrap items-center justify-between gap-3 py-2.5">
                      <span className="flex items-center gap-2.5 font-medium">
                        <Avatar url={q.avatar_url} name={q.display_name} size={32} />
                        {q.display_name}
                      </span>
                      <span className="flex gap-2">
                        <Button onClick={() => void inline((v) => roomsApi.decide(id, q.id, true, v), ["Đã duyệt", q.display_name])} disabled={busy || room.members.length >= MAX_MEMBERS} title={room.members.length >= MAX_MEMBERS ? "Phòng đã đủ 8 người." : undefined}>
                          Duyệt
                        </Button>
                        <Button variant="secondary" onClick={() => void inline((v) => roomsApi.decide(id, q.id, false, v))} disabled={busy}>
                          Từ chối
                        </Button>
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {isHost && room.invites.length > 0 ? (
              <section className="rounded-card bg-surface p-4 shadow-card sm:p-5" aria-labelledby="inv-title">
                <h2 id="inv-title" className="text-base font-bold">
                  Lời mời đang chờ · {room.invites.length}
                </h2>
                <ul className="mt-3 flex flex-wrap gap-2">
                  {room.invites.map((q) => (
                    <li key={q.id} className="inline-flex items-center gap-2 rounded-full border border-border py-1 pr-3 pl-1 text-sm">
                      <Avatar url={q.avatar_url} name={q.display_name} size={24} />
                      {q.display_name}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            <section className="rounded-card bg-surface p-4 shadow-card sm:p-5" aria-labelledby="mem-title">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 id="mem-title" className="text-base font-bold">
                  Thành viên · {room.members.length}/{MAX_MEMBERS}
                </h2>
                {isHost ? (
                  <Button variant="secondary" onClick={() => setDialog({ kind: "invite" })} disabled={room.members.length >= MAX_MEMBERS}>
                    + Mời người chơi
                  </Button>
                ) : null}
              </div>
              <ul className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {room.members.map((m) => (
                  <MemberTile
                    key={m.id}
                    m={m}
                    isMe={m.is_me}
                    canManage={isHost && !m.is_me}
                    onKick={() => setDialog({ kind: "kick", m })}
                    onTransfer={() => setDialog({ kind: "transfer", m })}
                    onDragStart={editor && !lineupIds.has(m.id) ? (e) => drag.begin(e, { kind: "member", id: m.id }, m.display_name) : undefined}
                  />
                ))}
                {Array.from({ length: Math.max(0, MAX_MEMBERS - room.members.length) }, (_, i) => (
                  <li key={`empty-${i}`} className="flex h-14 items-center gap-2.5 rounded-lg border border-dashed border-border-strong px-3 text-sm text-subtle">
                    <span aria-hidden className="size-8 rounded-full border border-dashed border-border-strong" />
                    Chỗ trống
                  </li>
                ))}
              </ul>
            </section>
          </>
        )}
      </div>

      {drag.ghost}
      {slotDlg && lu?.editable ? (
        <SlotDialog
          key={JSON.stringify(slotDlg)}
          state={slotDlg}
          draft={lu.base}
          members={room.members}
          onClose={() => setSlotDlg(null)}
          onPlace={(mid, ref) => {
            setSlotDlg(null);
            editLineup((d) => place(d, mid, ref));
          }}
          onSwitchTeam={(ref) => {
            setSlotDlg(null);
            editLineup((d) => switchTeam(d, ref));
          }}
          onRemove={(ref) => {
            setSlotDlg(null);
            editLineup((d) => remove(d, ref));
          }}
        />
      ) : null}
      {dialog?.kind === "leave" ? (
        <ConfirmDialog
          title="Rời phòng?"
          body={room.my_role === "host" ? "Bạn là Host. Rời phòng sẽ chuyển quyền Host cho một thành viên còn lại (chọn ngẫu nhiên); không còn ai thì phòng đóng." : "Bạn sẽ không còn trong phòng này. Muốn vào lại, bạn cần xin vào hoặc được mời."}
          confirmLabel="Rời phòng"
          danger
          onClose={() => setDialog(null)}
          onConfirm={leave}
        />
      ) : null}
      {dialog?.kind === "kick" ? (
        <ConfirmDialog
          title={`Mời ${dialog.m.display_name} ra khỏi phòng?`}
          body={`${dialog.m.display_name} sẽ không còn trong phòng này. Kết quả các trận đã lưu vẫn giữ trong Lịch sử và Xếp hạng.`}
          confirmLabel="Mời ra"
          danger
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            const target = dialog.m;
            const r = await write((v) => roomsApi.kick(id, target.id, v));
            if (r.error) return r.error;
            if (r.done) toast("Đã mời ra khỏi phòng", target.display_name);
            setDialog(null);
            return null;
          }}
        />
      ) : null}
      {dialog?.kind === "transfer" ? (
        <ConfirmDialog
          title={`Chuyển quyền host cho ${dialog.m.display_name}?`}
          body={`${dialog.m.display_name} sẽ được bốc, bắt đầu / kết thúc trận và quản lý thành viên. Bạn trở thành thành viên thường.`}
          confirmLabel="Chuyển quyền"
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            const target = dialog.m;
            const r = await write((v) => roomsApi.transferHost(id, target.id, v));
            if (r.error) return r.error;
            if (r.done) toast("Đã chuyển quyền host", target.display_name);
            setDialog(null);
            return null;
          }}
        />
      ) : null}
      {dialog?.kind === "invite" ? (
        <InviteDialog
          onClose={() => setDialog(null)}
          onSend={async (phone) => {
            const r = await write((v) => roomsApi.invite(id, phone, v));
            if (r.error) return r.error;
            if (r.done) toast("Đã gửi lời mời", "Người chơi sẽ nhận thông báo");
            setDialog(null);
            return null;
          }}
        />
      ) : null}
      {dialog?.kind === "result" && cur?.status === "playing" ? (
        <ResultDialog
          match={cur}
          onClose={() => setDialog(null)}
          onSave={async (a, b) => {
            const r = await write((v) => roomsApi.saveResult(id, cur.no, a, b, v));
            if (r.error) return r.error;
            if (r.done) {
              toast(`Đã lưu trận #${cur.no}`, `Đội ${a > b ? "A" : "B"} thắng ${Math.max(a, b)} – ${Math.min(a, b)}`);
              setTab("play");
            }
            setDialog(null);
            return null;
          }}
        />
      ) : null}
    </>
  );
}

function MemberTile({ m, isMe, canManage, onKick, onTransfer, onDragStart }: { m: RoomMember; isMe: boolean; canManage: boolean; onKick: () => void; onTransfer: () => void; onDragStart?: (e: React.PointerEvent) => void }) {
  const [menu, setMenu] = useState(false);
  return (
    <li
      onPointerDown={onDragStart}
      className={cn("relative flex h-14 items-center gap-2.5 rounded-lg border px-3", isMe ? "border-primary/25 bg-primary-softer" : "border-border", onDragStart && "cursor-grab select-none")}
    >
      <Avatar url={m.avatar_url} name={m.display_name} size={32} />
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          <span className="truncate text-sm font-semibold">{m.display_name}</span>
          {m.role === "host" ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-accent/25 px-2 py-0.5 text-xs font-semibold">
              <Crown className="size-3" />
              Host
            </span>
          ) : null}
          {isMe ? <span className="rounded-full bg-surface px-2 py-0.5 text-xs font-semibold ring-1 ring-border">Bạn</span> : null}
        </span>
        {m.queue_state === "playing" ? <span className="text-xs text-muted">Đang chơi</span> : null}
      </span>
      {canManage ? (
        <div className="relative" onBlur={(e) => !e.currentTarget.contains(e.relatedTarget) && setMenu(false)}>
          <button
            type="button"
            aria-label={`Tùy chọn cho ${m.display_name}`}
            aria-haspopup="menu"
            aria-expanded={menu}
            onClick={() => setMenu((o) => !o)}
            onKeyDown={(e) => e.key === "Escape" && setMenu(false)}
            className="grid size-8 place-items-center rounded-lg text-muted hover:bg-primary-softer hover:text-foreground focus-ring"
          >
            <span aria-hidden>···</span>
          </button>
          {menu ? (
            <div role="menu" className="absolute top-full right-0 z-20 mt-1 w-52 rounded-card bg-surface p-1.5 text-sm shadow-card ring-1 ring-border">
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMenu(false);
                  onTransfer();
                }}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left hover:bg-primary-softer focus-ring"
              >
                <Crown className="size-4" />
                Chuyển quyền host
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMenu(false);
                  onKick();
                }}
                className="w-full rounded-lg px-3 py-2 text-left text-danger hover:bg-primary-softer focus-ring"
              >
                Mời ra khỏi phòng
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}
