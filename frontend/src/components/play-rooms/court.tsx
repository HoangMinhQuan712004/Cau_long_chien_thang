import { Avatar } from "@/components/member-area/avatar";
import type { Format, Person, Player, RoomMember } from "./types";

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
        absolute flex max-w-[34%] -translate-x-1/2 -translate-y-1/2 items-center gap-1.5 rounded-full bg-surface py-0.5
        pr-2.5 pl-0.5 text-xs font-semibold text-foreground shadow-card
        sm:text-sm
      "
    >
      <Avatar url={p.avatar_url} name={p.display_name} size={22} />
      <span className="truncate">{p.display_name}</span>
      {host ? <Crown /> : null}
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
export function Court({ format, teamA, teamB, hostId, state, matchNo, hint, waiting }: Props) {
  const pos = POS[format];
  return (
    <div className="bg-primary-hover px-3 pt-4 pb-4 text-surface sm:px-6">
      <div className="mx-auto flex max-w-4xl items-center gap-2 sm:gap-6">
        <TeamLabel letter="A" />
        <div className="relative aspect-[2/1] min-w-0 flex-1 overflow-hidden rounded-md bg-primary shadow-card" role="img" aria-label={`Sân ${format === "2v2" ? "2 vs 2" : "1 vs 1"}`}>
          <svg viewBox="0 0 400 200" preserveAspectRatio="none" className="absolute inset-0 size-full text-surface/85" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
            <rect x="12" y="10" width="376" height="180" />
            <path d="M12 28h376M12 172h376M60 10v180M340 10v180M200 10v180M60 100h140M200 100h140" />
          </svg>
          {state !== "idle" && matchNo ? (
            <span className="absolute top-1.5 left-1/2 -translate-x-1/2 rounded-full bg-primary-hover/80 px-2.5 py-0.5 text-[11px] font-semibold tracking-wide whitespace-nowrap uppercase">
              {state === "playing" ? `Đang chơi · Trận #${matchNo}` : `Trận #${matchNo}`}
            </span>
          ) : null}
          {teamA.map((p, i) => (pos.a[i] ? <Chip key={p.member_id ?? `a${i}`} p={p} host={p.member_id === hostId} left={pos.a[i][0]} top={pos.a[i][1]} /> : null))}
          {teamB.map((p, i) => (pos.b[i] ? <Chip key={p.member_id ?? `b${i}`} p={p} host={p.member_id === hostId} left={pos.b[i][0]} top={pos.b[i][1]} /> : null))}
          {state === "idle" ? (
            <span className="absolute top-1/2 left-1/2 w-[70%] -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary-hover/85 px-3 py-1.5 text-center text-xs sm:text-sm">{hint}</span>
          ) : null}
        </div>
        <TeamLabel letter="B" />
      </div>
      <div className="mx-auto mt-3 flex max-w-4xl flex-wrap items-center gap-2 text-sm">
        <span className="text-xs font-semibold tracking-wide text-surface/70 uppercase">Chờ lượt</span>
        {waiting.length === 0 ? (
          <span className="text-surface/85">Không ai phải chờ</span>
        ) : (
          waiting.map((p) => (
            <span key={p.id} className="inline-flex items-center gap-1.5 rounded-full bg-surface/15 py-0.5 pr-2.5 pl-0.5 text-xs font-medium">
              <Avatar url={p.avatar_url} name={p.display_name} size={20} />
              {p.display_name}
            </span>
          ))
        )}
      </div>
    </div>
  );
}
