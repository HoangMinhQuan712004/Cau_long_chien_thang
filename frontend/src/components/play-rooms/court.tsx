import { Avatar } from "@/components/member-area/avatar";
import { cn } from "@/lib/cn";
import type { SlotRef } from "./lineup";
import type { Format, Person, Player, RoomMember } from "./types";

export type EditorPlayer = Person & { member_id: number };

/** Chế độ Host xếp đội hình (T-027): ô nhận người, kéo thả + bấm chọn. */
export type CourtEditor = {
  a: (EditorPlayer | null)[];
  b: (EditorPlayer | null)[];
  /** Ô đang được rê tới khi kéo ("a-0"). */
  over: string;
  onSlot: (ref: SlotRef, el: HTMLElement) => void;
  onRemove: (ref: SlotRef) => void;
  onDragStart: (e: React.PointerEvent, ref: SlotRef, label: string) => void;
};

type Props = {
  format: Format;
  teamA: Player[];
  teamB: Player[];
  /** `members[].id` của Host */
  hostId: number;
  /** "idle" chưa bốc · "drawn" đã bốc · "playing" đang chơi */
  state: "idle" | "drawn" | "playing";
  matchNo?: number;
  hint: string;
  waiting: RoomMember[];
  editor?: CourtEditor;
  /** Chip "Chờ lượt" kéo được (Host): trả `onPointerDown` cho từng người. */
  onWaitingDrag?: (e: React.PointerEvent, m: RoomMember) => void;
  /** Bấm chip "Chờ lượt" (Host): mở hộp chọn ô. */
  onWaitingPick?: (m: RoomMember) => void;
};

// Vị trí (%) của chip trên sân, theo thể thức
const POS: Record<Format, { a: [number, number][]; b: [number, number][] }> = {
  "2v2": {
    a: [
      [24, 28],
      [24, 72],
    ],
    b: [
      [76, 28],
      [76, 72],
    ],
  },
  "1v1": { a: [[24, 50]], b: [[76, 50]] },
};

function Crown() {
  return (
    <svg viewBox="0 0 20 20" className="size-3.5 shrink-0 text-accent" fill="currentColor" aria-hidden>
      <path d="m3 6 3.5 3L10 4l3.5 5L17 6l-1.5 9h-11z" />
    </svg>
  );
}

function Chip({ p, host, left, top }: { p: Person; host: boolean; left: number; top: number }) {
  return (
    <span
      style={{ left: `${left}%`, top: `${top}%` }}
      className="
        absolute flex w-max max-w-[44%] -translate-x-1/2 -translate-y-1/2 items-center gap-1 rounded-full bg-surface py-0.5
        pr-2 pl-0.5 text-[11px] font-semibold text-foreground shadow-card
        sm:max-w-[34%] sm:gap-1.5 sm:pr-2.5 sm:text-sm
      "
    >
      <Avatar url={p.avatar_url} name={p.display_name} size={22} />
      <span className="min-w-0 truncate">{p.display_name}</span>
      {host ? <Crown /> : null}
    </span>
  );
}

function Slot({ team, idx, p, host, left, top, editor }: { team: "a" | "b"; idx: number; p: EditorPlayer | null; host: boolean; left: number; top: number; editor: CourtEditor }) {
  const ref: SlotRef = { team, idx };
  const name = `Đội ${team.toUpperCase()}, ô ${idx + 1}`;
  const over = editor.over === `${team}-${idx}`;
  return (
    <span
      data-slot={`${team}-${idx}`}
      style={{ left: `${left}%`, top: `${top}%` }}
      // w-max + max-w: chip rộng theo tên nhưng không quá ~nửa sân, tên dài cắt "…" (không đè chip đội bên kia)
      className={cn("absolute flex w-max max-w-[44%] -translate-x-1/2 -translate-y-1/2 items-center rounded-full sm:max-w-[38%]", over && "ring-2 ring-surface ring-offset-2 ring-offset-primary")}
    >
      {p ? (
        <span className="flex max-w-full min-w-0 items-center rounded-full bg-surface pr-0.5 pl-0.5 shadow-card">
          <button
            type="button"
            aria-label={`${name}: ${p.display_name}. Mở menu`}
            aria-haspopup="dialog"
            onClick={(e) => editor.onSlot(ref, e.currentTarget)}
            onPointerDown={(e) => editor.onDragStart(e, ref, p.display_name)}
            className="flex min-h-8 min-w-0 cursor-grab items-center gap-1 rounded-full py-0.5 pr-1.5 pl-0.5 text-[11px] font-semibold text-foreground select-none focus-ring sm:gap-1.5 sm:pr-1 sm:text-sm"
          >
            <Avatar url={p.avatar_url} name={p.display_name} size={22} />
            <span className="min-w-0 truncate">{p.display_name}</span>
            {host ? <Crown /> : null}
          </button>
          {/* Điện thoại: không có ×, bấm tên mở menu (có "Bỏ khỏi sân") để chip đủ chỗ cho tên */}
          <button
            type="button"
            aria-label={`Bỏ ${p.display_name} khỏi sân`}
            onClick={() => editor.onRemove(ref)}
            className="grid size-6 shrink-0 place-items-center rounded-full text-muted hover:bg-primary-softer hover:text-foreground focus-ring max-sm:hidden"
          >
            <span aria-hidden>×</span>
          </button>
        </span>
      ) : (
        <button
          type="button"
          aria-label={`${name} trống. Thêm người`}
          aria-haspopup="dialog"
          onClick={(e) => editor.onSlot(ref, e.currentTarget)}
          className="min-h-8 rounded-full border-2 border-dashed border-surface/85 bg-primary-hover/40 px-2.5 text-xs font-semibold whitespace-nowrap text-surface hover:bg-primary-hover/70 focus-ring sm:text-sm"
        >
          + Thêm người
        </button>
      )}
    </span>
  );
}

function TeamLabel({ letter }: { letter: string }) {
  return (
    <p className="w-8 shrink-0 text-center text-[11px] leading-tight font-semibold tracking-wide uppercase sm:w-14 sm:text-xs" aria-hidden>
      <span className="block text-surface/70">Đội</span>
      <span className="text-lg sm:text-2xl">{letter}</span>
    </p>
  );
}

/** Sân cầu lông vẽ ngang: Đội A bên trái, Đội B bên phải; dưới sân là hàng "CHỜ LƯỢT" (ds-10, ds-09, ds-08). */
export function Court({ format, teamA, teamB, hostId, state, matchNo, hint, waiting, editor, onWaitingDrag, onWaitingPick }: Props) {
  const pos = POS[format];
  return (
    <div className="bg-primary-hover px-3 pt-4 pb-4 text-surface sm:px-6">
      <div className="mx-auto flex max-w-4xl items-center gap-2 sm:gap-6">
        <TeamLabel letter="A" />
        <div data-court className="relative aspect-[2/1] min-w-0 flex-1 overflow-hidden rounded-md bg-primary shadow-card" role={editor ? "group" : "img"} aria-label={`Sân ${format === "2v2" ? "2 vs 2" : "1 vs 1"}`}>
          <svg viewBox="0 0 400 200" preserveAspectRatio="none" className="absolute inset-0 size-full text-surface/85" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
            <rect x="12" y="10" width="376" height="180" />
            <path d="M12 28h376M12 172h376M60 10v180M340 10v180M200 10v180M60 100h140M200 100h140" />
          </svg>
          {state !== "idle" && matchNo ? (
            <span className="absolute top-1.5 left-1/2 -translate-x-1/2 rounded-full bg-primary-hover/80 px-2.5 py-0.5 text-[11px] font-semibold tracking-wide whitespace-nowrap uppercase">
              {state === "playing" ? `Đang chơi · Trận #${matchNo}` : `Trận #${matchNo}`}
            </span>
          ) : null}
          {editor
            ? (["a", "b"] as const).map((t) =>
                editor[t].map((p, i) => <Slot key={`${t}${i}`} team={t} idx={i} p={p} host={p?.member_id === hostId} left={pos[t][i][0]} top={pos[t][i][1]} editor={editor} />),
              )
            : null}
          {editor ? null : teamA.map((p, i) => (pos.a[i] ? <Chip key={p.member_id ?? `a${i}`} p={p} host={p.member_id === hostId} left={pos.a[i][0]} top={pos.a[i][1]} /> : null))}
          {editor ? null : teamB.map((p, i) => (pos.b[i] ? <Chip key={p.member_id ?? `b${i}`} p={p} host={p.member_id === hostId} left={pos.b[i][0]} top={pos.b[i][1]} /> : null))}
        </div>
        <TeamLabel letter="B" />
      </div>
      {state === "idle" ? (
        <p className="mx-auto mt-3 w-fit max-w-full rounded-full bg-primary-hover/85 px-4 py-1.5 text-center text-xs sm:text-sm">{hint}</p>
      ) : null}
      <div className="mx-auto mt-3 flex max-w-4xl flex-wrap items-center gap-2 text-sm">
        <span className="text-xs font-semibold tracking-wide text-surface/70 uppercase">Chờ lượt</span>
        {waiting.length === 0 ? (
          <span className="text-surface/85">Không ai phải chờ</span>
        ) : (
          waiting.map((p) => (
            <span key={p.id} className="inline-flex items-center rounded-full bg-surface/15 text-xs font-medium">
              {onWaitingPick ? (
                <button
                  type="button"
                  aria-label={`${p.display_name}: xếp vào sân`}
                  aria-haspopup="dialog"
                  onClick={() => onWaitingPick(p)}
                  onPointerDown={(e) => onWaitingDrag?.(e, p)}
                  className="inline-flex min-h-8 cursor-grab items-center gap-1.5 rounded-full py-0.5 pr-2.5 pl-0.5 select-none hover:bg-surface/25 focus-ring"
                >
                  <Avatar url={p.avatar_url} name={p.display_name} size={20} />
                  {p.display_name}
                </button>
              ) : (
                <span className="inline-flex items-center gap-1.5 py-0.5 pr-2.5 pl-0.5">
                  <Avatar url={p.avatar_url} name={p.display_name} size={20} />
                  {p.display_name}
                </span>
              )}
            </span>
          ))
        )}
      </div>
    </div>
  );
}
